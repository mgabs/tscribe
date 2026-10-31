"""Tests for configuration loading and management."""

import pytest

from tscribe.config import TscribeConfig


def test_defaults():
    config = TscribeConfig()
    assert config.recording.sample_rate == 16000
    assert config.recording.channels == 1
    assert config.recording.auto_transcribe is True
    assert config.transcription.model == "small"
    assert config.transcription.output_formats == ["txt", "json"]
    assert config.transcription.gpu is False
    assert config.storage.data_dir == ""


def test_load_missing_file(tmp_path):
    config = TscribeConfig.load(tmp_path / "nonexistent.toml")
    assert config.recording.sample_rate == 16000


def test_load_none_path():
    config = TscribeConfig.load(None)
    assert config.recording.sample_rate == 16000


def test_save_and_load_roundtrip(tmp_path):
    config = TscribeConfig()
    config.recording.sample_rate = 44100
    config.transcription.model = "small"
    config_path = tmp_path / "config.toml"
    config.save(config_path)

    loaded = TscribeConfig.load(config_path)
    assert loaded.recording.sample_rate == 44100
    assert loaded.transcription.model == "small"
    # Unchanged defaults preserved
    assert loaded.recording.channels == 1
    assert loaded.transcription.gpu is False


def test_get_dotted_key():
    config = TscribeConfig()
    assert config.get("recording.sample_rate") == 16000
    assert config.get("transcription.model") == "small"
    assert config.get("storage.data_dir") == ""


def test_get_invalid_key_format():
    config = TscribeConfig()
    with pytest.raises(KeyError, match="Invalid key format"):
        config.get("sample_rate")


def test_get_unknown_section():
    config = TscribeConfig()
    with pytest.raises(KeyError, match="Unknown config section"):
        config.get("nonexistent.key")


def test_get_unknown_key():
    config = TscribeConfig()
    with pytest.raises(KeyError, match="Unknown config key"):
        config.get("recording.nonexistent")


def test_set_dotted_key():
    config = TscribeConfig()
    config.set("recording.sample_rate", 44100)
    assert config.recording.sample_rate == 44100


def test_set_string_coercion_to_int():
    config = TscribeConfig()
    config.set("recording.sample_rate", "44100")
    assert config.recording.sample_rate == 44100


def test_set_string_coercion_to_bool():
    config = TscribeConfig()
    config.set("recording.auto_transcribe", "false")
    assert config.recording.auto_transcribe is False
    config.set("recording.auto_transcribe", "true")
    assert config.recording.auto_transcribe is True


def test_set_string_coercion_to_list():
    config = TscribeConfig()
    config.set("transcription.output_formats", "txt,srt")
    assert config.transcription.output_formats == ["txt", "srt"]


def test_set_invalid_model():
    config = TscribeConfig()
    with pytest.raises(ValueError, match="Invalid model"):
        config.set("transcription.model", "nonexistent")


def test_set_invalid_output_format():
    config = TscribeConfig()
    with pytest.raises(ValueError, match="Invalid output format"):
        config.set("transcription.output_formats", "txt,invalid")


def test_set_negative_sample_rate():
    config = TscribeConfig()
    with pytest.raises(ValueError, match="sample_rate must be positive"):
        config.set("recording.sample_rate", -1)


def test_set_negative_channels():
    config = TscribeConfig()
    with pytest.raises(ValueError, match="channels must be positive"):
        config.set("recording.channels", 0)


def test_partial_toml_loads_with_defaults(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[recording]\nsample_rate = 48000\n')

    config = TscribeConfig.load(config_path)
    assert config.recording.sample_rate == 48000
    assert config.recording.channels == 1  # default preserved
    assert config.transcription.model == "small"  # section not in file


def test_unknown_keys_in_toml_ignored(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text('[recording]\nsample_rate = 48000\nunknown_key = "ignored"\n')

    config = TscribeConfig.load(config_path)
    assert config.recording.sample_rate == 48000


def test_to_dict():
    config = TscribeConfig()
    d = config._to_dict()
    assert d["recording"]["sample_rate"] == 16000
    assert d["transcription"]["output_formats"] == ["txt", "json"]
    assert "storage" in d


@pytest.mark.parametrize(('key', 'value'), [
    ('recording.sample_rate', True),
    ('recording.channels', 1.5),
    ('recording.default_device', 42),
    ('transcription.gpu', 1),
    ('transcription.output_formats', []),
    ('app.recent_limit', 0),
    ('app.notifications', 'invalid'),
])
def test_invalid_config_values(key, value):
    with pytest.raises(ValueError):
        TscribeConfig().set(key, value)


@pytest.mark.parametrize('content', [
    '[recording]\nsample_rate = -1\n',
    'recording = false\n',
    '[app]\nrecent_limit = 0\n',
])
def test_invalid_file_rejected(tmp_path, content):
    path = tmp_path / 'config.toml'
    path.write_text(content)
    with pytest.raises(ValueError):
        TscribeConfig.load(path)


def test_app_settings_roundtrip(tmp_path):
    config = TscribeConfig()
    config.set('app.notifications', 'false')
    config.set('app.recent_limit', '10')
    config.set('app.show_elapsed_time', 'false')
    path = tmp_path / 'config.toml'
    config.save(path)
    loaded = TscribeConfig.load(path)
    assert loaded.app.notifications is False
    assert loaded.app.recent_limit == 10
    assert loaded.app.show_elapsed_time is False


@pytest.mark.parametrize('value', ['true', 'TRUE', '1', 'yes', 'Yes'])
def test_boolean_true_aliases(value):
    config = TscribeConfig()
    config.set('app.notifications', value)
    assert config.app.notifications is True


@pytest.mark.parametrize('value', ['false', 'FALSE', '0', 'no', 'No'])
def test_boolean_false_aliases(value):
    config = TscribeConfig()
    config.set('app.notifications', value)
    assert config.app.notifications is False


@pytest.mark.parametrize('key', [
    'recording.sample_rate', 'recording.channels', 'app.recent_limit',
])
def test_positive_integer_boundaries(key):
    config = TscribeConfig()
    config.set(key, 1)
    assert config.get(key) == 1
    for invalid in (0, -1):
        with pytest.raises(ValueError, match='must be positive'):
            config.set(key, invalid)
        assert config.get(key) == 1


@pytest.mark.parametrize('method', ['get', 'set'])
@pytest.mark.parametrize(('key', 'message'), [
    ('sample_rate', 'Invalid key format'),
    ('recording.', 'Invalid key format'),
    ('nonexistent.key', 'Unknown config section'),
    ('save.key', 'Unknown config section'),
    ('recording.nonexistent', 'Unknown config key'),
    ('recording.sample_rate.extra', 'Unknown config key'),
])
def test_invalid_keys_have_actionable_errors(method, key, message):
    config = TscribeConfig()
    args = (key,) if method == 'get' else (key, '1')
    with pytest.raises(KeyError, match=message):
        getattr(config, method)(*args)


def test_save_creates_nested_parents(tmp_path):
    path = tmp_path / 'new' / 'settings' / 'tscribe' / 'config.toml'
    config = TscribeConfig()
    config.set('transcription.language', 'de')
    config.save(path)
    assert TscribeConfig.load(path).transcription.language == 'de'


def test_invalid_boolean_error_identifies_key_and_value():
    with pytest.raises(ValueError) as error:
        TscribeConfig().set('app.notifications', 'maybe')
    assert 'app.notifications' in str(error.value)
    assert 'maybe' in str(error.value)


def test_type_error_identifies_setting_and_required_type():
    with pytest.raises(ValueError) as error:
        TscribeConfig().set('recording.channels', 1.5)
    assert 'recording.channels' in str(error.value)
    assert 'int' in str(error.value)


def test_invalid_section_error_identifies_section(tmp_path):
    path = tmp_path / 'config.toml'
    path.write_text('recording = false\n')
    with pytest.raises(ValueError, match="section 'recording' must be a table"):
        TscribeConfig.load(path)


def test_empty_formats_error_is_actionable():
    with pytest.raises(ValueError, match='^output_formats must contain at least one format$'):
        TscribeConfig().set('transcription.output_formats', [])


@pytest.mark.parametrize(('key', 'value'), [
    ('captions.audio_source', 'loopback'),
    ('captions.output_mode', 'bluetooth'),
    ('captions.font_size', 11),
    ('captions.font_size', 73),
    ('captions.font_size', True),
    ('captions.always_on_top', 'maybe'),
])
def test_caption_preferences_reject_invalid_values(key, value):
    with pytest.raises(ValueError):
        TscribeConfig().set(key, value)


def test_existing_config_gets_caption_defaults(tmp_path):
    path = tmp_path / 'config.toml'
    path.write_text('[transcription]\nmodel = "tiny"\n')
    config = TscribeConfig.load(path)
    assert config.captions.audio_source == 'both'
    assert config.captions.output_mode == 'headphones'
    assert config.captions.font_size == 24
    assert config.captions.always_on_top is True
    assert config.transcription.model == 'tiny'


@pytest.mark.parametrize('value', ['false', 'true'])
def test_echo_preference_roundtrip(tmp_path, value):
    config = TscribeConfig()
    config.set('captions.echo_cancellation', value)
    config.save(tmp_path / 'config.toml')
    assert TscribeConfig.load(tmp_path / 'config.toml').captions.echo_cancellation is (value == 'true')


def test_diarize_engine_config_default_and_validation():
    import pytest
    from tscribe.config import TscribeConfig

    config = TscribeConfig()
    assert config.transcription.diarize_engine == 'nemotron'
    config.set('transcription.diarize_engine', 'wespeaker')
    assert config.get('transcription.diarize_engine') == 'wespeaker'
    with pytest.raises(ValueError, match='nemotron.*wespeaker'):
        config.set('transcription.diarize_engine', 'bogus')
