"""Executable entry point for the bundled, headless Python worker."""

if __name__ == '__main__':
    # PyInstaller's resource tracker must not start a second protocol server.
    # Libraries such as tqdm can initialize multiprocessing during inference.
    from multiprocessing import freeze_support

    freeze_support()

    from tscribe.worker import main

    main()
