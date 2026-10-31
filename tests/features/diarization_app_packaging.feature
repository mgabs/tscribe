Feature: Packaged macOS app diarization
  REQ-DIAR-4, NFR-DIAR-2

  Scenario: Packaged app runs Nemotron without a separately installed runtime
    Given the packaged app and diarize_engine is "nemotron"
    And no nemo-speech runtime is installed on the machine
    When a sample recording is diarized
    Then speaker turns are produced
    And no weights are downloaded

  Scenario: Bundle size recorded
    Given the app is packaged with and without the Nemotron runtime and weights
    When the sizes are compared
    Then the difference is recorded in design.md
