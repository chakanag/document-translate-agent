import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.extraction import extract_text_blocks
from app.services.language import detect_language
from app.services.translation import DemoTranslationProvider, available_providers, ollama_generate_timeout, translate_blocks


class PipelineTests(unittest.TestCase):
    def test_detects_japanese_text(self) -> None:
        self.assertEqual(detect_language("これは日本語の文書です。"), "ja")

    def test_extracts_and_demo_translates_text_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "sample.txt"
            path.write_text("こんにちは\n\n世界", encoding="utf-8")
            blocks = extract_text_blocks(path, "txt")
            translated = translate_blocks(blocks, "ja", "ko", DemoTranslationProvider())

        self.assertEqual(len(translated), 2)
        self.assertEqual(translated[0].translatedText, "[ko] こんにちは")
        self.assertEqual(translated[1].translatedText, "[ko] 世界")

    def test_demo_provider_is_available_without_key(self) -> None:
        providers = available_providers()
        self.assertTrue(any(provider["id"] == "demo" for provider in providers))

    def test_ollama_generate_timeout_defaults_to_none(self) -> None:
        with patch("app.services.translation.provider_value", return_value=None), patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(ollama_generate_timeout())

    def test_ollama_generate_timeout_can_be_configured(self) -> None:
        with patch("app.services.translation.provider_value", return_value=30), patch.dict("os.environ", {}, clear=True):
            self.assertEqual(ollama_generate_timeout(), 30.0)


if __name__ == "__main__":
    unittest.main()
