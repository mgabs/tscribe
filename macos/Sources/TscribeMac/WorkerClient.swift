import Foundation

struct AppFailure: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

@MainActor
final class WorkerClient {
    private let executableOverride: URL?
    private let argumentsOverride: [String]
    init(executable: URL? = nil, arguments: [String] = []) {
        executableOverride = executable
        argumentsOverride = arguments
    }
    private var process: Process?
    private var input: FileHandle?
    private var pending: [String: (Result<[String: Any], Error>) -> Void] = [:]
    private var partial = Data()
    var onEvent: ((String, [String: Any]) -> Void)?

    func start() throws {
        if process?.isRunning == true { return }
        let task = Process()
        let bundled = Bundle.main.resourceURL?.appendingPathComponent("Worker/tscribe-worker")
        if let executableOverride {
            task.executableURL = executableOverride
            task.arguments = argumentsOverride
        } else if let bundled, FileManager.default.isExecutableFile(atPath: bundled.path) {
            task.executableURL = bundled
        } else if let python = ProcessInfo.processInfo.environment["TSCRIBE_PYTHON_EXECUTABLE"] {
            task.executableURL = URL(fileURLWithPath: python)
            task.arguments = ["-m", "tscribe.worker"]
        } else {
            throw AppFailure(message: "The bundled transcription worker is missing. Rebuild the app using packaging/macos/build_native.py.")
        }
        let incoming = Pipe(), outgoing = Pipe(), errors = Pipe()
        task.standardInput = incoming
        task.standardOutput = outgoing
        task.standardError = errors
        outgoing.fileHandleForReading.readabilityHandler = { [weak self, weak task] handle in
            let data = handle.availableData
            guard !data.isEmpty else { handle.readabilityHandler = nil; return }
            DispatchQueue.main.async {
                guard let task, self?.process === task else { return }
                self?.receive(data)
            }
        }
        let logDirectory = ProcessInfo.processInfo.environment["TSCRIBE_LOG_DIR"].map { URL(fileURLWithPath: $0) }
            ?? FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/tscribe")
        try? FileManager.default.createDirectory(at: logDirectory, withIntermediateDirectories: true)
        let logURL = logDirectory.appendingPathComponent("worker.log")
        if !FileManager.default.fileExists(atPath: logURL.path) { FileManager.default.createFile(atPath: logURL.path, contents: nil) }
        let log = try? FileHandle(forWritingTo: logURL)
        _ = try? log?.seekToEnd()
        errors.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil; try? log?.close() }
            else if let log { try? log.write(contentsOf: data) }
            else { FileHandle.standardError.write(data) }
        }
        task.terminationHandler = { [weak self] process in
            DispatchQueue.main.async {
                guard let self, self.process === process else { return }
                self.input = nil
                self.process = nil
                self.partial.removeAll()
                let error = AppFailure(message: "The transcription worker stopped (status \(process.terminationStatus)). Audio files remain saved. Reopen tscribe to retry.")
                let callbacks = Array(self.pending.values)
                self.pending.removeAll()
                for callback in callbacks { callback(.failure(error)) }
                self.onEvent?("worker-stopped", ["message": error.localizedDescription])
            }
        }
        try task.run()
        process = task
        input = incoming.fileHandleForWriting
    }

    func request(_ command: String, values: [String: Any] = [:]) async throws -> [String: Any] {
        try start()
        return try await withCheckedThrowingContinuation { continuation in
            let id = UUID().uuidString
            var message = values
            message["id"] = id
            message["command"] = command
            do {
                var data = try JSONSerialization.data(withJSONObject: message)
                data.append(0x0a)
                pending[id] = { continuation.resume(with: $0) }
                try input?.write(contentsOf: data)
            } catch {
                pending.removeValue(forKey: id)
                continuation.resume(throwing: error)
            }
        }
    }

    private func receive(_ data: Data) {
        partial.append(data)
        while let end = partial.firstIndex(of: 0x0a) {
            let line = partial[..<end]
            partial.removeSubrange(...end)
            guard let message = try? JSONSerialization.jsonObject(with: line) as? [String: Any],
                  let event = message["event"] as? String else { continue }
            let data = message["data"] as? [String: Any] ?? [:]
            if let id = message["id"] as? String, event == "result" {
                pending.removeValue(forKey: id)?(.success(data))
            } else if let id = message["id"] as? String, event == "error" {
                pending.removeValue(forKey: id)?(.failure(AppFailure(message: message["error"] as? String ?? "Worker failed")))
            } else { onEvent?(event, data) }
        }
    }

    func stop() {
        let current = process
        process = nil
        try? input?.close()
        input = nil
        partial.removeAll()
        let callbacks = Array(pending.values)
        pending.removeAll()
        for callback in callbacks { callback(.failure(AppFailure(message: "Transcription request cancelled."))) }
        if current?.isRunning == true { current?.terminate() }
    }
}
