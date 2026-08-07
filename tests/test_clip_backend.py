import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from app.tbc.detection.clip_backend import (
    ClipImageEncoder,
    ClipTextEncoder,
    _model_files,
    _preprocess_image,
    _PreprocessConfig,
    clip_models_ready,
    rank_by_similarity,
)


class PreprocessConfigTests(unittest.TestCase):
    def test_load_reads_size_mean_std_from_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "preprocess_cfg.json"
            path.write_text(
                json.dumps(
                    {
                        "size": [224, 224],
                        "mean": [0.48145466, 0.4578275, 0.40821073],
                        "std": [0.26862954, 0.26130258, 0.27577711],
                    }
                )
            )
            config = _PreprocessConfig.load(path)
        self.assertEqual(config.size, (224, 224))
        self.assertAlmostEqual(config.mean[0], 0.48145466)
        self.assertAlmostEqual(config.std[2], 0.27577711)


class PreprocessImageTests(unittest.TestCase):
    def test_returns_normalized_nchw_float32_tensor_of_target_size(self):
        config = _PreprocessConfig(size=(224, 224), mean=(0.5, 0.5, 0.5), std=(0.5, 0.5, 0.5))
        image = np.zeros((480, 640, 3), dtype=np.uint8)
        tensor = _preprocess_image(image, config)
        self.assertEqual(tensor.shape, (1, 3, 224, 224))
        self.assertEqual(tensor.dtype, np.float32)

    def test_normalization_maps_black_pixels_to_minus_one(self):
        config = _PreprocessConfig(size=(4, 4), mean=(0.5, 0.5, 0.5), std=(0.5, 0.5, 0.5))
        image = np.zeros((10, 10, 3), dtype=np.uint8)
        tensor = _preprocess_image(image, config)
        self.assertTrue(np.allclose(tensor, -1.0))


class ModelFilesTests(unittest.TestCase):
    def test_layout_matches_immich_app_visual_textual_split(self):
        paths = _model_files(Path("/models"), "ViT-B-32__openai")
        self.assertEqual(paths["visual"], Path("/models/clip/ViT-B-32__openai/visual.onnx"))
        self.assertEqual(paths["textual"], Path("/models/clip/ViT-B-32__openai/textual.onnx"))
        self.assertEqual(paths["tokenizer"], Path("/models/clip/ViT-B-32__openai/tokenizer.json"))
        self.assertEqual(paths["preprocess_cfg"], Path("/models/clip/ViT-B-32__openai/preprocess_cfg.json"))


class ClipModelsReadyTests(unittest.TestCase):
    def test_false_when_files_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(clip_models_ready(Path(tmp), "ViT-B-32__openai"))

    def test_true_once_all_four_files_are_present_and_nonempty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "clip" / "ViT-B-32__openai"
            root.mkdir(parents=True)
            for name in ("visual.onnx", "textual.onnx", "tokenizer.json", "preprocess_cfg.json"):
                (root / name).write_bytes(b"x")
            self.assertTrue(clip_models_ready(Path(tmp), "ViT-B-32__openai"))

    def test_false_when_a_file_is_present_but_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "clip" / "ViT-B-32__openai"
            root.mkdir(parents=True)
            for name in ("visual.onnx", "textual.onnx", "tokenizer.json", "preprocess_cfg.json"):
                (root / name).write_bytes(b"x" if name != "textual.onnx" else b"")
            self.assertFalse(clip_models_ready(Path(tmp), "ViT-B-32__openai"))


class ClipImageEncoderTests(unittest.TestCase):
    def test_encode_image_feeds_a_preprocessed_tensor_and_returns_the_embedding(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "preprocess_cfg.json"
            cfg_path.write_text(json.dumps({"size": [224, 224], "mean": [0.5, 0.5, 0.5], "std": [0.5, 0.5, 0.5]}))
            model_path = Path(tmp) / "visual.onnx"
            model_path.write_bytes(b"fake")

            encoder = ClipImageEncoder(model_path, cfg_path)
            fake_session = MagicMock()
            fake_session.run.return_value = [np.array([[1.0, 0.0, 0.0]], dtype=np.float32)]

            with patch("onnxruntime.InferenceSession", return_value=fake_session) as mock_session_cls:
                image = np.zeros((100, 100, 3), dtype=np.uint8)
                embedding = encoder.encode_image(image)

            mock_session_cls.assert_called_once()
            self.assertEqual(embedding.tolist(), [1.0, 0.0, 0.0])
            positional_args, keyword_args = fake_session.run.call_args
            self.assertIsNone(positional_args[0])
            fed = positional_args[1]
            self.assertIn("image", fed)
            self.assertEqual(fed["image"].shape, (1, 3, 224, 224))

    def test_session_is_loaded_only_once_across_repeated_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg_path = Path(tmp) / "preprocess_cfg.json"
            cfg_path.write_text(json.dumps({"size": [224, 224], "mean": [0.5, 0.5, 0.5], "std": [0.5, 0.5, 0.5]}))
            model_path = Path(tmp) / "visual.onnx"
            model_path.write_bytes(b"fake")

            encoder = ClipImageEncoder(model_path, cfg_path)
            fake_session = MagicMock()
            fake_session.run.return_value = [np.array([[0.0, 1.0]], dtype=np.float32)]
            image = np.zeros((50, 50, 3), dtype=np.uint8)

            with patch("onnxruntime.InferenceSession", return_value=fake_session) as mock_session_cls:
                encoder.encode_image(image)
                encoder.encode_image(image)

            mock_session_cls.assert_called_once()


class ClipTextEncoderTests(unittest.TestCase):
    def test_encode_text_tokenizes_with_clip_padding_and_runs_the_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "textual.onnx"
            model_path.write_bytes(b"fake")
            tokenizer_path = Path(tmp) / "tokenizer.json"
            tokenizer_path.write_text("{}")

            encoder = ClipTextEncoder(model_path, tokenizer_path)
            fake_session = MagicMock()
            fake_session.run.return_value = [np.array([[0.0, 1.0]], dtype=np.float32)]

            fake_encoded = MagicMock()
            fake_encoded.ids = [49406] + [49407] * 76
            fake_tokenizer = MagicMock()
            fake_tokenizer.encode.return_value = fake_encoded

            with (
                patch("onnxruntime.InferenceSession", return_value=fake_session),
                patch("tokenizers.Tokenizer.from_file", return_value=fake_tokenizer),
            ):
                embedding = encoder.encode_text("a red van")

            fake_tokenizer.enable_padding.assert_called_once_with(length=77, pad_id=49407, pad_token="<|endoftext|>")
            fake_tokenizer.enable_truncation.assert_called_once_with(max_length=77)
            fake_tokenizer.encode.assert_called_once_with("a red van")
            self.assertEqual(embedding.tolist(), [0.0, 1.0])

            positional_args, _ = fake_session.run.call_args
            fed = positional_args[1]
            self.assertEqual(fed["text"].shape, (1, 77))
            self.assertEqual(fed["text"].dtype, np.int32)


class RankBySimilarityTests(unittest.TestCase):
    def test_orders_by_descending_dot_product(self):
        rows = [
            {"recording_id": 1, "embedding": [1.0, 0.0]},
            {"recording_id": 2, "embedding": [0.0, 1.0]},
            {"recording_id": 3, "embedding": [0.7071, 0.7071]},
        ]
        query = np.array([1.0, 0.0], dtype=np.float32)
        ranked = rank_by_similarity(query, rows, limit=10)
        self.assertEqual([recording_id for recording_id, _ in ranked], [1, 3, 2])

    def test_respects_limit(self):
        rows = [{"recording_id": i, "embedding": [float(i), 0.0]} for i in range(5)]
        ranked = rank_by_similarity(np.array([1.0, 0.0], dtype=np.float32), rows, limit=2)
        self.assertEqual(len(ranked), 2)
        self.assertEqual([recording_id for recording_id, _ in ranked], [4, 3])

    def test_empty_rows_returns_empty_list(self):
        self.assertEqual(rank_by_similarity(np.array([1.0, 0.0], dtype=np.float32), [], limit=10), [])


if __name__ == "__main__":
    unittest.main()
