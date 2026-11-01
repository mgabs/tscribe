Feature: Nemotron engine
  REQ-DIAR-3, REQ-DIAR-5, REQ-DIAR-6, REQ-DIAR-7

  Scenario: Packaged app runs offline with bundled weights
    Given the packaged app with bundled runtime and weights
    And the network is unavailable
    When Nemotron diarizes a recording
    Then speaker turns are produced without any download

  Scenario: Development first run downloads weights once
    Given Nemotron is selected outside the packaged app
    And the weights are absent
    When Nemotron diarizes a recording twice
    Then the weights are downloaded once and reused

  Scenario: Download failure leaves no partial file
    Given Nemotron is selected outside the packaged app
    When the weight download fails or yields an empty or invalid file
    Then a clear error is raised
    And no partial file remains at the final path
    And no other engine is substituted

  Scenario: Bundled weights missing
    Given the packaged app whose bundled weights are absent or invalid
    When Nemotron diarizes a recording
    Then a clear error names the missing component
    And no other engine is substituted

  Scenario: Missing runtime
    Given Nemotron is selected and the nemo-speech runtime cannot be found
    When diarization runs
    Then the error names the runtime and how to install it

  Scenario: Speaker cap
    Given num_speakers is 9
    When Nemotron diarizes a recording
    Then an error states the maximum of 8 speakers

  Scenario: Offline with weights present
    Given the weights are bundled or already cached
    And the network is unavailable
    When Nemotron diarizes a recording
    Then diarization completes
