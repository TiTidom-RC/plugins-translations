import json
import os
from pathlib import Path
import pytest

from plugintranslations.translator import PluginTranslator
from plugintranslations.consts import (
    EN_US,
    FR_FR,
    ES_ES,
    DE_DE,
    PLUGIN_ROOT,
    INPUT_SOURCE_LANGUAGE,
    INPUT_TARGET_LANGUAGES,
    INPUT_INCLUDE_EMPTY_TRANSLATION,
    INPUT_USE_CORE_TRANSLATIONS,
    INPUT_GENERATE_SOURCE_LANGUAGE_TRANSLATIONS,
    INPUT_DEBUG,
    TRANSLATIONS_FILES_PATH,
)


class TestPluginTranslator():
    # Arrange
    @pytest.fixture(scope="session", autouse=True)
    def current_working_dir(self, tmp_path_factory) -> Path:
        _cwd = tmp_path_factory.mktemp("plugin_root")
        return _cwd

    @pytest.fixture(autouse=True)
    def setup_os_env(self):
        os.environ[INPUT_SOURCE_LANGUAGE] = FR_FR
        os.environ[INPUT_TARGET_LANGUAGES] = f'{EN_US},{ES_ES},{DE_DE}'
        os.environ[INPUT_INCLUDE_EMPTY_TRANSLATION] = 'False'
        os.environ[INPUT_USE_CORE_TRANSLATIONS] = 'False'
        os.environ[INPUT_GENERATE_SOURCE_LANGUAGE_TRANSLATIONS] = 'False'
        os.environ[INPUT_DEBUG] = 'True'

    @pytest.fixture(autouse=True)
    def setup_info_json(self, current_working_dir: Path):
        self.__plugin_root = current_working_dir/PLUGIN_ROOT
        plugin_info_root = current_working_dir/PLUGIN_ROOT/"plugin_info"
        plugin_info_root.mkdir(parents=True, exist_ok=True)
        assert plugin_info_root.exists()

        info_json_content = {}
        info_json_content['language'] = [FR_FR, EN_US, ES_ES, DE_DE]
        info_json_content['id'] = 'fake_plugin'

        info_json_file = plugin_info_root/'info.json'
        info_json_file.write_text(json.dumps(info_json_content, ensure_ascii=False, indent='\t'), encoding="UTF-8")

    def test_init(self, current_working_dir):
        self._test_translate = PluginTranslator(current_working_dir)
        assert self._test_translate is not None
        assert isinstance(self._test_translate, PluginTranslator)

    def test_get_plugin_translations(self, current_working_dir):
        # Arrange
        self._test_translate = PluginTranslator(current_working_dir)

        translation_path = self.__plugin_root/TRANSLATIONS_FILES_PATH
        translation_path.mkdir(parents=True, exist_ok=True)
        (translation_path/f"{EN_US}.json").write_text('{}', encoding="UTF-8")

        # Act
        self._test_translate.get_plugin_translations()
        # Assert: no exception raised
        assert self._test_translate is not None
