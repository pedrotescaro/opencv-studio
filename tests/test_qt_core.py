"""Pixel-level regression checks for the Qt editor's independent image core."""

from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from studio.document import Document, Operation
from studio.filters import (
    ADJUSTMENTS,
    FILTERS,
    PRESETS,
    apply_operation,
    adjustment_defaults,
    grow_region,
    histogram,
    output_size,
    render_pipeline,
    selection_mask,
)
from studio.io import read_image, write_image


class QtCoreTests(unittest.TestCase):
    def setUp(self):
        self.image = np.random.default_rng(17).integers(
            0, 256, (48, 64, 3), dtype=np.uint8
        )
        self.image[5:20, 5:25] = (40, 70, 150)
        self.alpha = np.indices((48, 64))[1].astype(np.uint8) * 4
        self.rgba = np.dstack((self.image, self.alpha))

    def test_every_catalog_filter_executes_independently(self):
        original = self.image.copy()
        self.assertGreaterEqual(sum(map(len, FILTERS.values())), 104)
        for category, names in FILTERS.items():
            for name in names:
                with self.subTest(category=category, filter=name):
                    output = apply_operation(
                        self.image, Operation("filter", {"name": name})
                    )
                    self.assertEqual(output.dtype, np.uint8)
                    self.assertGreater(output.size, 0)
                    self.assertFalse(np.shares_memory(output, self.image))
                    np.testing.assert_array_equal(self.image, original)

    def test_catalog_filters_accept_gray_and_preserve_transparency(self):
        for names in FILTERS.values():
            for name in names:
                with self.subTest(filter=name):
                    op = Operation("filter", {"name": name})
                    out = apply_operation(
                        cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY), op
                    )
                    self.assertEqual(out.dtype, np.uint8)
                    transparent = apply_operation(self.rgba, op)
                    self.assertEqual(transparent.shape[2], 4)
                    if name not in FILTERS["Transformar"] and name != "Split BGR":
                        np.testing.assert_array_equal(transparent[:, :, 3], self.alpha)

    def test_default_adjustments_curves_levels_are_exact_identity(self):
        for image in (self.image, self.rgba, self.image[:, :, 0]):
            for kind, params in (
                ("adjustments", adjustment_defaults()),
                ("curves", {}),
                ("levels", {}),
            ):
                with self.subTest(kind=kind, shape=image.shape):
                    np.testing.assert_array_equal(
                        apply_operation(image, Operation(kind, params)), image
                    )

    def test_every_adjustment_changes_pixels_without_changing_alpha(self):
        for key, spec in ADJUSTMENTS.items():
            value = spec["max"]
            with self.subTest(adjustment=key):
                out = apply_operation(self.rgba, Operation("adjustments", {key: value}))
                np.testing.assert_array_equal(out[:, :, 3], self.alpha)
                self.assertFalse(np.array_equal(out[:, :, :3], self.image))

    def test_all_presets_are_combinations_and_distinct(self):
        results = []
        for name, params in PRESETS.items():
            with self.subTest(preset=name):
                out = apply_operation(self.image, Operation("preset", {"name": name}))
                self.assertGreater(len(params), 2)
                self.assertFalse(np.array_equal(out, self.image))
                results.append(out.tobytes())
        self.assertEqual(len(set(results)), len(PRESETS))

    def test_selection_and_intensity_only_modify_selected_pixels(self):
        selection = {"shape": "rect", "rect": (10, 8, 12, 16), "source_size": (64, 48)}
        operation = Operation(
            "filter", {"name": "Inverter cores"}, intensity=0.5, selection=selection
        )
        out = apply_operation(self.rgba, operation)
        np.testing.assert_array_equal(out[:8], self.rgba[:8])
        np.testing.assert_array_equal(
            out[8:24, 10:22, :3], np.full((16, 12, 3), 128, np.uint8)
        )
        np.testing.assert_array_equal(out[:, :, 3], self.alpha)
        operation.intensity = 0
        np.testing.assert_array_equal(apply_operation(self.rgba, operation), self.rgba)

    def test_ellipse_mask_and_preview_selection_coordinates(self):
        selection = {
            "shape": "ellipse",
            "rect": (16, 12, 32, 24),
            "source_size": (64, 48),
        }
        full = selection_mask(self.image.shape, selection)
        small = selection_mask((24, 32, 3), selection)
        self.assertEqual(int(full[12, 16]), 0)
        self.assertEqual(int(full[24, 32]), 255)
        self.assertEqual(int(small[12, 16]), 255)
        self.assertFalse(np.any(full[:12]))
        self.assertLess(abs(np.count_nonzero(full) / 4 - np.count_nonzero(small)), 10)

    def test_non_destructive_recipe_and_geometry_preview(self):
        original = self.rgba.copy()
        operations = [
            Operation("crop", {"rect": (8, 8, 40, 32)}),
            Operation("resize", {"width": 80, "height": 64}),
            Operation("rotate", {"angle": 90}),
            Operation("flip", {"axis": "horizontal"}),
            Operation("adjustments", {"brightness": 20}),
        ]
        full = render_pipeline(self.rgba, operations)
        preview = render_pipeline(self.rgba, operations, max_size=32)
        self.assertEqual(full.shape, (80, 64, 4))
        self.assertEqual(preview.shape, (32, 26, 4))
        self.assertEqual(output_size(self.rgba.shape, operations), (64, 80))
        np.testing.assert_array_equal(self.rgba, original)

    def test_output_dimensions_cover_legacy_and_arbitrary_rotation(self):
        for name in FILTERS["Transformar"] + ["Split BGR"]:
            operations = [Operation("filter", {"name": name})]
            actual = render_pipeline(self.image, operations)
            self.assertEqual(
                output_size(self.image.shape, operations),
                (actual.shape[1], actual.shape[0]),
                name,
            )
        for angle in (0, 90, 180, 270, 34, -17, 360):
            operations = [Operation("rotate", {"angle": angle})]
            actual = render_pipeline(self.image, operations)
            self.assertEqual(
                output_size(self.image.shape, operations),
                (actual.shape[1], actual.shape[0]),
            )

    def test_preview_upscale_is_bounded_before_resampling(self):
        operations = [Operation("resize", {"width": 8000, "height": 6000})]
        preview = render_pipeline(self.image, operations, max_size=320)
        self.assertEqual(preview.shape, (240, 320, 3))

    def test_levels_curves_and_channel_curve(self):
        pixels = np.array([[[10, 100, 220], [255, 0, 128]]], np.uint8)
        inverted = apply_operation(
            pixels, Operation("curves", {"points": [(0, 255), (255, 0)]})
        )
        np.testing.assert_array_equal(inverted, 255 - pixels)
        red = apply_operation(
            pixels,
            Operation("curves", {"points": [(0, 255), (255, 0)], "channel": "R"}),
        )
        np.testing.assert_array_equal(red[:, :, :2], pixels[:, :, :2])
        np.testing.assert_array_equal(red[:, :, 2], 255 - pixels[:, :, 2])
        levels = apply_operation(
            pixels, Operation("levels", {"black": 10, "white": 220, "gamma": 1})
        )
        self.assertEqual(int(levels[0, 0, 0]), 0)
        self.assertEqual(int(levels[0, 0, 2]), 255)
        with self.assertRaises(ValueError):
            apply_operation(pixels, Operation("levels", {"black": 220, "white": 10}))

    def test_histogram_visible_counts_and_hsv_hue_ranges(self):
        for model in ("RGB", "HSV", "Cinza"):
            hist = histogram(self.rgba, model)
            for channel, counts in hist.items():
                self.assertEqual(int(counts.sum()), 48 * 63)
                self.assertEqual(len(counts), 180 if channel == "H" else 256)

    def test_arithmetic_saturates_and_region_is_connected(self):
        source = np.full((10, 20, 3), 200, np.uint8)
        out = apply_operation(
            source, Operation("arithmetic", {"image": source, "mode": "add"})
        )
        np.testing.assert_array_equal(out, np.full_like(source, 255))
        out = apply_operation(
            source, Operation("arithmetic", {"image": source, "mode": "subtract"})
        )
        np.testing.assert_array_equal(out, np.zeros_like(source))
        source[:] = 0
        source[2:5, 3:6] = 50
        source[6:9, 13:16] = 50
        mask = grow_region(source, (4, 3), 0)
        self.assertEqual(np.count_nonzero(mask), 9)
        self.assertEqual(mask[7, 14], 0)

    def test_text_supports_unicode_and_raster_preview(self):
        base = np.zeros((200, 400, 3), np.uint8)
        out = apply_operation(
            base,
            Operation(
                "text",
                {
                    "text": "Visão — edição",
                    "x": 10,
                    "y": 90,
                    "size": 40,
                    "color": (0, 100, 255),
                },
            ),
        )
        self.assertTrue(np.any(out))
        self.assertEqual(int(out[:, :, 0].max()), 0)
        result = render_pipeline(
            self.image, [Operation("raster", {"image": out})], max_size=100
        )
        self.assertEqual(result.shape, (50, 100, 3))
        self.assertEqual(
            output_size(self.image.shape, [Operation("raster", {"image": out})]),
            (400, 200),
        )

    def test_history_is_unlimited_clickable_and_branches_after_undo(self):
        document = Document()
        document.open(self.image, "test.png")
        for i in range(140):
            document.commit(
                Operation("adjustments", {"brightness": i % 50}, name=str(i))
            )
        self.assertEqual(len(document.history.entries), 141)
        self.assertTrue(document.undo())
        self.assertTrue(document.redo())
        self.assertTrue(document.jump(12))
        self.assertEqual(len(document.operations), 12)
        document.commit(
            Operation("filter", {"name": "Inverter cores"}, name="Inverter")
        )
        self.assertEqual(len(document.history.entries), 14)
        self.assertFalse(document.redo())
        self.assertFalse(document.jump(900))
        self.assertTrue(document.modified)
        document.mark_saved()
        self.assertFalse(document.modified)

    def test_history_owns_parameters_but_shares_immutable_raster_operands(self):
        document = Document()
        document.open(self.image)
        operand = self.image.copy()
        operation = Operation("arithmetic", {"image": operand, "mode": "add"})
        document.commit(operation)
        operand[:] = 0
        stored = document.operations[0].params["image"]
        self.assertFalse(stored.flags.writeable)
        np.testing.assert_array_equal(stored, self.image)
        document.commit(Operation("adjustments", {"brightness": 12}))
        self.assertIs(stored, document.history.entries[2].operations[0].params["image"])
        copy = document.duplicate()
        self.assertIsNot(copy.original, document.original)
        copy.operations[0].params["mode"] = "subtract"
        self.assertEqual(document.operations[0].params["mode"], "add")

    def test_unicode_io_alpha_formats_and_quality(self):
        with tempfile.TemporaryDirectory() as folder:
            for extension in ("png", "webp", "tiff", "jpg", "bmp"):
                with self.subTest(extension=extension):
                    target = Path(folder) / f"edição_á.{extension}"
                    write_image(target, self.rgba, quality=91)
                    result = read_image(target)
                    self.assertEqual(result.shape[:2], self.image.shape[:2])
                    if extension in ("png", "tiff"):
                        np.testing.assert_array_equal(result, self.rgba)
                    if extension in ("jpg", "bmp"):
                        self.assertEqual(result.shape[2], 3)
                        self.assertGreater(int(result[:, 0, :].mean()), 245)
            invalid = Path(folder) / "invalido.png"
            invalid.write_bytes(b"not an image")
            with self.assertRaises(ValueError):
                read_image(invalid)

    def test_sixteen_bit_input_maps_fixed_range(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "16bit.png"
            image = np.array([[0, 257, 32768, 65535]], np.uint16)
            cv2.imencode(".png", image)[1].tofile(str(path))
            np.testing.assert_array_equal(read_image(path), [[0, 1, 128, 255]])

    def test_invalid_operations_return_useful_errors(self):
        invalids = [
            Operation("missing"),
            Operation("crop", {"rect": (-1, 0, 20, 20)}),
            Operation("resize", {"width": 0, "height": 30}),
            Operation("text", {"text": ""}),
            Operation("levels", {"gamma": 0}),
            Operation("curves", {"points": [(0, 0), (0, 255)]}),
            Operation("adjustments", {"gamma": float("nan")}),
            Operation("region", {"seed": (-1, 0)}),
        ]
        for op in invalids:
            with self.subTest(kind=op.kind):
                with self.assertRaises(ValueError):
                    apply_operation(self.image, op)


if __name__ == "__main__":
    unittest.main()
