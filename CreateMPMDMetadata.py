# Cura PostProcessingPlugin
# Author:   Daniel Cervenkov
# Date:     December 30, 2021

# Description:  This plugin adds a thumbnail image, material, material amount,
# and infill density metadata to a GCODE file in a way compatible with the
# Monoprice Mini Delta v2 Firmware.

import base64, math, os, sys, time

from UM.Application import Application
from UM.Logger import Logger
from cura.Snapshot import Snapshot
from PyQt6.QtCore import QByteArray, QIODevice, QBuffer
from PyQt6.QtGui import QImage

from ..Script import Script


SJPG_FILE_FORMAT_VERSION = "V1.00"
THUMBNAIL_WIDTH = 140
THUMBNAIL_HEIGHT = 140


class CreateMPMDMetadata(Script):
    def __init__(self):
        super().__init__()

    def _createSnapshot(self, width, height):
        Logger.log("d", "Creating thumbnail image...")
        try:
            return Snapshot.snapshot(width, height)
        except Exception:
            Logger.logException("e", "Failed to create snapshot image")

    def _convertImageToSJPG(self, snapshot, width, height, quality, fragment_height=16):
        """Convert QImage to split JPG (a LVGL format).

        Decoding normal JPG requres the whole uncompressed image fit in the
        device RAM. MPMDv2 uses SJPG to work aroung this. SJPG is a bundle of
        small JPEG fragments with an SJPG header.

        This function was adapted from
        https://github.com/lvgl/lvgl/blob/master/scripts/jpg_to_sjpg.py

        Args:
            snapshot: QImage to be converted.
            width: The snapshot width in pixels.
            height: The snapshot height in pixels.
            fragment_height: Max height of fragments in pixels.

        Returns:
            Bytearray with the SJPG image.
        """
        Logger.log("d", "Converting thumbnail image to SJPG...")
        try:
            lenbuf = []
            parts = math.ceil(height / fragment_height)

            sjpeg_data = bytearray()
            sjpeg = bytearray()

            row_remaining = height
            for i in range(parts):
                crop = snapshot.copy(
                    0, i * fragment_height, width, min(row_remaining, fragment_height)
                )
                row_remaining = row_remaining - fragment_height

                thumbnail_buffer = QBuffer()
                thumbnail_buffer.open(QBuffer.OpenModeFlag.ReadWrite)

                crop.save(thumbnail_buffer, format="JPG", quality=quality)

                sjpeg_data = sjpeg_data + thumbnail_buffer.data()
                lenbuf.append(len(thumbnail_buffer.data()))
                thumbnail_buffer.close()

            header = bytearray()

            # 4 BYTES
            header = header + bytearray("_SJPG__".encode("UTF-8"))

            # 6 BYTES VERSION
            header = header + bytearray(
                ("\x00" + SJPG_FILE_FORMAT_VERSION + "\x00").encode("UTF-8")
            )

            # WIDTH 2 BYTES
            header = header + width.to_bytes(2, byteorder="little")

            # HEIGHT 2 BYTES
            header = header + height.to_bytes(2, byteorder="little")

            # NUMBER OF ITEMS 2 BYTES
            header = header + parts.to_bytes(2, byteorder="little")

            # NUMBER OF ITEMS 2 BYTES
            header = header + int(fragment_height).to_bytes(2, byteorder="little")

            for item_len in lenbuf:
                # WIDTH 2 BYTES
                header = header + item_len.to_bytes(2, byteorder="little")

            sjpeg = header + sjpeg_data
            return sjpeg
        except Exception:
            Logger.logException("e", "Failed to convert snapshot to SJPG")

    def _encodeSnapshot(self, snapshot, width, height):
        """Encode image in base16 ASCII.

        Args:
            snapshot: Image to be encoded.
            width: The snapshot width in pixels.
            height: The snapshot height in pixels.
        """
        Logger.log("d", "Encoding thumbnail image...")
        try:
            base16_bytes = base64.b16encode(snapshot)
            base16_message = base16_bytes.decode("ascii").lower()
            return base16_message
        except Exception:
            Logger.logException("e", "Failed to encode snapshot image")

    def _convertSnapshotToGcode(self, encoded_snapshot, width, height, chunk_size=80):
        """Convert ASCII encoded image to GCODE.

        As per MPMDv2 firmware expectations, the block starts with W221, each
        line is prepended with W220 and the thumbnail ends with W222.

        Args:
            snapshot: Image to be encoded.
            width: The snapshot width in pixels.
            height: The snapshot height in pixels.
            chunk_size: Number of characters to put on each line.
        """
        gcode = []

        encoded_snapshot_length = len(encoded_snapshot)
        gcode.append("; thumbnail begin")
        gcode.append("W221")

        chunks = [
            "W220 {}".format(encoded_snapshot[i : i + chunk_size])
            for i in range(0, len(encoded_snapshot), chunk_size)
        ]
        gcode.extend(chunks)

        gcode.append("W222")
        gcode.append("; thumbnail end")
        gcode.append("")

        return gcode

    def getSettingDataString(self):
        return """{
            "name": "Create MPMD Metadata",
            "key": "CreateMPMDMetadata",
            "metadata": {},
            "version": 2,
            "settings": {
                "quality":
                {
                    "label": "Quality",
                    "description": "Quality of the generated JPG image.",
                    "type": "int",
                    "default_value": 30,
                    "minimum_value": 1,
                    "maximum_value": 100
                }
            }
        }"""

    def execute(self, data):
        Logger.log("d", "Retrieving print settings")
        try:
            assert len(Application.getInstance().getGlobalContainerStack().extruderList) == 1
            extruder = Application.getInstance().getGlobalContainerStack().extruderList[0]

            material = extruder.material.getMetaData().get("material", "")
            infill_density = extruder.getProperty("infill_sparse_density", "value")
        except:
            Logger.logException("e", "Couldn't retrieve print settings")

        quality = self.getSettingValueByKey("quality")

        width = THUMBNAIL_WIDTH
        height = THUMBNAIL_HEIGHT

        snapshot = self._createSnapshot(width, height)
        if snapshot:
            sjpg_snapshot = self._convertImageToSJPG(snapshot, width, height, quality)
            encoded_snapshot = self._encodeSnapshot(sjpg_snapshot, width, height)
            snapshot_gcode = self._convertSnapshotToGcode(
                encoded_snapshot, width, height
            )

            for layer in data:
                layer_index = data.index(layer)
                lines = data[layer_index].split("\n")
                for line in lines:
                    if line.startswith(";Filament used: "):
                        line_index = lines.index(line)
                        amount_m = float(line.rsplit(" ", 1)[1].replace("m", ""))
                        amount_mm = amount_m * 1000
                        lines[line_index] = f";FilamentUsed:{amount_mm:.2f}"
                        lines.insert(line_index, f";FilamentType:{material}")
                        lines.insert(line_index, f";InfillDensity:{infill_density}")
                    if line.startswith(";Generated with Cura"):
                        line_index = lines.index(line)
                        insert_index = line_index + 1
                        lines[insert_index:insert_index] = snapshot_gcode
                        break

                final_lines = "\n".join(lines)
                data[layer_index] = final_lines

        return data
