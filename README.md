## Cura Post Processing Script for Monoprice Mini Delta

This script adds a thumbnail image, material, material amount, and infill density metadata to a G-Code file in a way compatible with the Monoprice Mini Delta v2 Firmware. Simply put, the display on the printer will show a thumbnail and other relevant information.

## Usage

1. Copy the `CreateMPMDMetadata.py` file to the Cura `scripts` folder and restart Cura. `Help > Show Configuration Folder` can help you locate the folder.
2. Open the Post Processing Plugin dialog (`Extensions > Post Processing > Modify G-Code`)
3. Add a script `Create MPMD Metadata`
4. Profit. The script should be executed every time you slice. You can inspect the G-Code file - there should be a block of `W220` commands near the top of the file.
