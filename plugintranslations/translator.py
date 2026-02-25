import hashlib
import json
import logging
import os
import time
from pathlib import Path

import deepl

from .throttle import Throttle

from .version import VERSION
from .source_file import SourceFile
from .consts import (
    ALL_LANGUAGES,
    CORE_ROOT,
    FR_FR,
    INPUT_DEBUG,
    INPUT_DEEPL_API_KEY,
    INPUT_GENERATE_SOURCE_LANGUAGE_TRANSLATIONS,
    INPUT_INCLUDE_EMPTY_TRANSLATION,
    FILE_EXTS,
    INPUT_SOURCE_LANGUAGE,
    INPUT_TARGET_LANGUAGES,
    INPUT_USE_CORE_TRANSLATIONS,
    LANGUAGES_TO_DEEPL,
    LANGUAGES_TO_DEEPL_GLOSSARY,
    LOG_FORMAT,
    PLUGIN_DIRS,
    PLUGIN_INFO_JSON,
    PLUGIN_ROOT,
    TRANSLATIONS_FILES_PATH
)
from .translations import Translations


class PluginTranslator():

    def __init__(self, cwd: Path = Path.cwd()) -> None:
        self.__plugin_root = cwd/PLUGIN_ROOT

        self.__files: dict[str, SourceFile] = {}
        self.__existing_translations = Translations()
        self.__source_language: str
        self.__target_languages: list[str] = []
        self.__include_empty_translation: bool = False
        self.__use_core_translations: bool = True
        self.__generate_source_language_translations: bool = False

        self.__logger = logging.getLogger(__name__)
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
        logging.getLogger('deepl').setLevel(logging.WARNING)

        self.__core_root = cwd/CORE_ROOT

        self.__deepl_translator: deepl.Translator | None = None
        self.__deepl_api_key: str | None = None
        self.__api_call_counter = 0

        self.__info_json_file: Path = self.__plugin_root/PLUGIN_INFO_JSON
        self.__info_json_content: dict | None = None

        self.__get_inputs()
        self.__read_info_json()

        self.__glossary: dict[str, deepl.GlossaryInfo | None] = {lang: None for lang in self.__target_languages}

        self.__logger.info(f"Translate plugin module version {VERSION} initialized with deepl version {deepl.__version__}")

    @property
    def deepl_translator(self):
        if self.__deepl_translator is not None:
            return self.__deepl_translator

        if self.__deepl_api_key is not None:
            self.__deepl_translator = deepl.Translator(self.__deepl_api_key)
            self.__create_deepl_glossaries(self.__deepl_translator)
        return self.__deepl_translator

    @property
    def plugin_id(self) -> str:
        return self.__info_json_content['id'] if self.__info_json_content is not None else 'unknown'

    def start(self):
        self.get_plugin_translations()

        if self.__use_core_translations:
            self.get_core_translations()

        self.find_prompts_in_all_files()

        self.do_translate()
        self.translate_info_json()

        self.write_plugin_translations()

        self.__write_info_json()

    def __get_inputs(self):

        self.__source_language = self._get_input_in_list(INPUT_SOURCE_LANGUAGE, ALL_LANGUAGES)
        self.__target_languages = self._get_list_input(INPUT_TARGET_LANGUAGES, ALL_LANGUAGES)
        self.__deepl_api_key = self._get_input(INPUT_DEEPL_API_KEY)
        self.__include_empty_translation = self._get_boolean_input(INPUT_INCLUDE_EMPTY_TRANSLATION)
        if self.__source_language != FR_FR:
            self.__use_core_translations = False
        else:
            self.__use_core_translations = self._get_boolean_input(INPUT_USE_CORE_TRANSLATIONS)
        self.__generate_source_language_translations = self._get_boolean_input(INPUT_GENERATE_SOURCE_LANGUAGE_TRANSLATIONS)
        debug = self._get_boolean_input(INPUT_DEBUG)
        if debug:
            self.__logger.setLevel(logging.DEBUG)

        self.__logger.info("=== Run plugin translation with following options ===")
        self.__logger.info(f"source language: {self.__source_language}")
        self.__logger.info(f"target languages: {self.__target_languages}")
        self.__logger.info(f"include empty translation: {self.__include_empty_translation}")
        self.__logger.info(f"use core translations: {self.__use_core_translations}")
        self.__logger.info(f"generate source language translations: {self.__generate_source_language_translations}")
        self.__logger.info(f"debug: {debug}")
        self.__logger.info(f"deepl api key present: {self.__deepl_api_key is not None}")
        self.__logger.info("=====================================================")

    def _get_input(self, name: str):
        val = os.environ[name].strip() if name in os.environ else ''
        return val if val != '' else None

    def _get_boolean_input(self, name: str):
        val = self._get_input(name)
        true_values = ['true', 'True', 'TRUE']
        false_values = ['false', 'False', 'FALSE']
        if val in true_values:
            return True
        elif val in false_values:
            return False
        else:
            raise ValueError(f'Input does not meet specifications: {name}.\n Support boolean input list: "true | True | TRUE | false | False | FALSE"')

    def _get_list_input(self, name: str, allowed_values: list):
        val = self._get_input(name)
        if val is None:
            raise ValueError(f'Input does not meet specifications: {name}.\n {name} is required')
        values = [s.strip() for s in val.split(',')]
        for s in values:
            if s not in allowed_values:
                raise ValueError(f'Input does not meet specifications: {name}.\n {s} not in list: {allowed_values}')
        return values

    def _get_input_in_list(self, name: str, allowed_values: list):
        val = self._get_input(name)
        if val is None or val not in allowed_values:
            raise ValueError(f'Input does not meet specifications: {name}.\n {val} not in list: {allowed_values}')
        return val

    def __read_info_json(self):
        if not self.__info_json_file.is_file():
            raise RuntimeError("Missing info.json file")
        try:
            self.__info_json_content = json.loads(self.__info_json_file.read_text(encoding="UTF-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise RuntimeError(f"Invalid info.json file: {e}") from e

    def __write_info_json(self):
        if self.__info_json_content is None:
            self.__logger.warning("No info.json content to write, skipping...")
            return
        self.__info_json_content['language'] = sorted(set([self.__source_language] + self.__target_languages))
        self.__info_json_file.write_text(json.dumps(self.__info_json_content, ensure_ascii=False, indent='\t'), encoding="UTF-8")

    def __create_deepl_glossaries(self, deepl_translator: deepl.Translator):
        file_dir = Path(__file__).parent
        glossary_file = file_dir/f"{self.__source_language}_glossary.json"
        if not glossary_file.exists():
            return

        try:
            str_entries = glossary_file.read_text(encoding="UTF-8")
            entries = json.loads(str_entries)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            self.__logger.error(f"Cannot read glossary file {glossary_file.as_posix()}: {e}")
            return
        md5_hash = hashlib.md5(str_entries.encode('utf-8')).hexdigest()
        deepl_glossaries = deepl_translator.list_glossaries()

        for target_language in self.__target_languages:
            if target_language == self.__source_language or target_language not in entries:
                continue
            self.__logger.info(f"Check glossary {self.__source_language}=>{target_language}")

            for deepl_glossary in deepl_glossaries:
                if deepl_glossary.source_lang == LANGUAGES_TO_DEEPL_GLOSSARY[self.__source_language] and deepl_glossary.target_lang == LANGUAGES_TO_DEEPL_GLOSSARY[target_language]:
                    if deepl_glossary.name == md5_hash:
                        self.__logger.info("Already exists")
                        self.__glossary[target_language] = deepl_glossary
                        break
                    else:
                        self.__logger.info(f"Delete existing old glossary {deepl_glossary.name}")
                        deepl_translator.delete_glossary(deepl_glossary)
            if self.__glossary[target_language] is None:
                self.__logger.info(f"Create new glossary {md5_hash}")
                self.__glossary[target_language] = deepl_translator.create_glossary(md5_hash, source_lang=LANGUAGES_TO_DEEPL_GLOSSARY[self.__source_language],
                                                                                    target_lang=LANGUAGES_TO_DEEPL_GLOSSARY[target_language], entries=entries[target_language])

    def find_prompts_in_all_files(self):
        self.__logger.info("Find prompts in all plugin files")
        for directory in PLUGIN_DIRS:
            plugin_dir = self.__plugin_root/directory
            if not plugin_dir.exists():
                self.__logger.info(f"Directory {plugin_dir.as_posix()} not found, skipping...")
                continue
            for root, dirs, files in plugin_dir.walk():
                dirs[:] = [d for d in dirs if not (root.name == "core" and d == 'i18n')]

                for filename_str in files:
                    if filename_str == 'info.json':
                        continue
                    filename = Path(filename_str)
                    if filename.suffix in FILE_EXTS:
                        absolute_file_path = root/filename
                        jeedom_file_path = absolute_file_path.relative_to(self.__plugin_root)
                        jeedom_file_path = (f"plugins/{self.plugin_id}"/jeedom_file_path).as_posix()
                        self.__logger.info(f"    {jeedom_file_path}...")
                        self.__files[jeedom_file_path] = SourceFile(absolute_file_path, self.__logger)
                        self.__files[jeedom_file_path].search_prompts()

    def do_translate(self):
        self.__logger.info("Find existing translations...")
        for source_file in self.__files.values():
            for prompt in source_file.get_prompts().values():
                # first get translations from existing translations (plugin & core) if exists
                if prompt.get_text() in self.__existing_translations:
                    tr = self.__existing_translations.get_translations(prompt.get_text())
                    prompt.set_translations(tr)

                # make sure to store text as a target translation for source language
                prompt.set_translation(self.__source_language, prompt.get_text())

        if self.deepl_translator is not None:
            # collect all (prompt, language) pairs that still need a DeepL call
            pending: list[tuple] = []
            for source_file in self.__files.values():
                for prompt in source_file.get_prompts().values():
                    for target_language in self.__target_languages:
                        if target_language != self.__source_language and not prompt.has_translation(target_language):
                            pending.append((prompt, target_language))

            total = len(pending)
            self.__logger.info(f"{total} text(s) to translate via DeepL")
            call_count = 0
            for prompt, target_language in pending:
                text = prompt.get_text()
                # Re-check cache: same text may appear in multiple files; avoid redundant DeepL calls
                if not prompt.has_translation(target_language):
                    cached = self.__existing_translations.get_translations(text)
                    if target_language in cached and cached[target_language] != '':
                        prompt.set_translation(target_language, cached[target_language])
                        continue
                    call_count += 1
                    short_text = text[:60].replace('\n', ' ')
                    self.__logger.info(f"[{call_count}] -> {target_language}: '{short_text}'")
                    tr = self.translate_with_deepl(text, target_language)
                    prompt.set_translation(target_language, tr)
                    self.__existing_translations.add_translation(target_language, text, tr)

        self.__logger.info(f"Number of api call done: {self.__api_call_counter}")

    def translate_info_json(self):
        if self.deepl_translator is None:
            return
        if self.__info_json_content is None:
            return

        if 'description' not in self.__info_json_content:
            self.__logger.warning("You should add a 'Description' in info.json, see https://doc.jeedom.com/fr_FR/dev/structure_info_json")
            return
        descriptions = self.__info_json_content['description']
        if not isinstance(descriptions, dict):
            descriptions = {self.__source_language: descriptions}

        if self.__source_language not in descriptions:
            self.__logger.warning(f"You should have a 'Description' in info.json that matches your source language: {self.__source_language}")
            return
        source_desc = descriptions[self.__source_language]
        if not source_desc:
            self.__logger.warning("Description in info.json is empty, skipping translation")
            return

        for target_language in self.__target_languages:
            if target_language in descriptions and descriptions[target_language] != '':
                self.__logger.info(f"Description for {target_language} already translated, skipping")
                continue
            self.__logger.info(f"Translating info.json description to {target_language}")
            descriptions[target_language] = self.translate_with_deepl(source_desc, target_language)

        self.__info_json_content['description'] = descriptions

    @Throttle(seconds=0.5)
    def translate_with_deepl(self, text: str, target_language: str) -> str:
        if self.__deepl_translator is None:
            return ''

        max_retries = 5
        backoff = 5.0
        result = None
        for attempt in range(max_retries):
            try:
                self.__api_call_counter += 1
                result = self.__deepl_translator.translate_text(
                    text,
                    source_lang=LANGUAGES_TO_DEEPL[self.__source_language],
                    target_lang=LANGUAGES_TO_DEEPL[target_language],
                    preserve_formatting=True,
                    context='home automation',
                    glossary=self.__glossary[target_language],
                    model_type='prefer_quality_optimized'
                )
                break
            except deepl.TooManyRequestsException:
                if attempt < max_retries - 1:
                    wait = backoff * (2 ** attempt)
                    self.__logger.warning(f"DeepL rate limit hit, retrying in {wait:.0f}s (attempt {attempt + 1}/{max_retries})...")
                    time.sleep(wait)
                else:
                    self.__logger.error("DeepL rate limit hit, max retries reached, giving up on this text.")
                    return ''

        if result is None or not isinstance(result, deepl.TextResult):
            self.__logger.error(f"Unexpected result type: {type(result)}")
            return ''

        return result.text

    def get_plugin_translations(self):
        self.__logger.info("Read plugin translations file...")
        self._get_translations_from_json_files(self.__plugin_root/TRANSLATIONS_FILES_PATH)

    def get_core_translations(self):
        if not self.__core_root.exists():
            raise RuntimeError(f"Path {self.__core_root.as_posix()} does not exist")

        self.__logger.info("Read core translations file...")
        self._get_translations_from_json_files(self.__core_root/TRANSLATIONS_FILES_PATH)

    def _get_translations_from_json_files(self, translations_dir: Path):
        for language in self.__target_languages:
            translation_file = translations_dir/f"{language}.json"
            if not translation_file.exists():
                self.__logger.info(f"file {translation_file.as_posix()} not found !?")
                continue
            try:
                data = json.loads(translation_file.read_text(encoding="UTF-8"))
                for path in data:
                    for text in data[path]:
                        self.__existing_translations.add_translation(language, text, data[path][text])
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
                self.__logger.error(f"Error while reading {translation_file.as_posix()}: {e}")

    def write_plugin_translations(self):
        self.__logger.info("Write translations files...")

        translation_path = self.__plugin_root/TRANSLATIONS_FILES_PATH
        translation_path.mkdir(parents=True, exist_ok=True)

        for target_language in self.__target_languages:
            if target_language == self.__source_language and not self.__generate_source_language_translations:
                continue

            translation_file = translation_path/f"{target_language}.json"

            language_result = {}
            for path, source_file in self.__files.items():
                prompts = source_file.get_prompts_and_translation(target_language, self.__include_empty_translation)
                if len(prompts) > 0:
                    language_result[path] = prompts

            if len(language_result) > 0:
                self.__logger.info(f"Writing {translation_file.as_posix()} ({sum(len(v) for v in language_result.values())} entries)")
                translation_file.write_text(json.dumps(language_result, ensure_ascii=False, sort_keys=True, indent=4).replace('/', r'\/'), encoding="UTF-8")
            else:
                self.__logger.info(f"No translations for {target_language}, skipping file")
