Feature: Diarization engine selection
  REQ-DIAR-1, REQ-DIAR-2, REQ-DIAR-5, NFR-DIAR-1

  Scenario: Default engine
    Given diarize_engine is unset
    When diarization runs
    Then the Nemotron engine produces the speaker turns

  Scenario: WeSpeaker selected
    Given diarize_engine is "wespeaker"
    When diarization runs
    Then the WeSpeaker engine is used
    And the output is identical to the behaviour before this change

  Scenario: Invalid value
    Given diarize_engine is "pyannote"
    When diarization is requested
    Then an error names the valid values "nemotron" and "wespeaker"
    And no diarization is performed

  Scenario: Attribution is engine-agnostic
    Given either engine returns turns for the same audio
    When attribute_speakers labels the transcript segments
    Then no code path depends on which engine produced the turns

  Scenario: WeSpeaker path never loads the Nemotron runtime
    Given diarize_engine is "wespeaker"
    When diarization runs
    Then the Nemotron module is not imported
