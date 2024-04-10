in container // override with

```bash
pip install git+https://github.com/amaranth-farm/python-usb-descriptors.git

# testing
aplaymidi -p 20:0 <>.mid
amidi -d --port "hw:1,0,0"
```

# Eurorack PMOD - USB Soundcard

This project allows a [`eurorack-pmod`](https://github.com/apfelaudio/eurorack-pmod) to be used as an 8-channel (4in + 4out) USB2 sound card. Currently it has the following limitations:

- Only 48KHz / 16bit sample rate supported
- LambdaConcept ECPIX-5 is the only (tested) target platform
- For now, enumeration and audio only tested on Linux

## Connecting

- The `eurorack-pmod` should be connected to PMOD0.
    - **WARN**: if you are using an older (R3.1) hw revision, make sure to build with `PMOD_HW=HW_R31` in the build invocation below. Otherwise the gateware will freeze as it will try to talk to the touch IC (which is not there for R3.1).
- CN16 is the USB-C device port upon which the device will enumerate
- Power jumper set to `USB-2` so it's possible to disconnect & reconnect the LUNA USB port while the board is powered from the debug interface port.

## Prebuilt bitstreams

If you don't want to build yourself, I have attached some prebuilt and tested bitstreams to the GitHub releases.

## Building

Clone the repository and fetch all submodules:

```bash
git clone <this repository>
cd <this repository>
git submodule update --init --recursive
```

This project is based on a fork of LUNA. There are a few different ways you can keep your python environment isolated - python venv or by using a container. Here I will be using a container as it should be more consistent across other OSs/systems.

First, let's build the container (assuming you have docker installed)

```bash
build -f Dockerfile -t luna .
```

Now we can run the container with this repository mounted inside it. This allows us to run commands inside the container and the filesystem will be shared between host and container (you can build and then see the built bitstreams from the host).

```bash
# run this from inside the git repository
docker run -it --mount src="$(pwd)",target=/eurorack-pmod-usb-soundcard,type=bind luna
```

From the container, install the fork of LUNA and install all its dependencies:
```bash
cd eurorack-pmod-usb-soundcard
pip3 install deps/luna
```

Now you can build a bitstream, it will end up in `build/top.bit`.
```bash
# From the root directory of this repository
PMOD_HW=HW_R33 LUNA_PLATFORM="ecpix5:ECPIX5_85F_Platform" python3 rtl/top.py --dry-run --keep-files
```

From outside the container, if you have `openFPGALoader` installed you can flash this to ECPIX like so (with R03 boards)
```bash
openFPGALoader -b ecpix5_r03 <this_repo>/build/top.bit
```

If you plug in the USB-C, you should see something like:

```bash
# Check it enumerates
$ dmesg
...
[ 5489.544374] usb 5-1: new high-speed USB device number 9 using xhci_hcd
[ 5489.687203] usb 5-1: New USB device found, idVendor=1209, idProduct=1234, bcdDevice= 0.01
[ 5489.687208] usb 5-1: New USB device strings: Mfr=1, Product=2, SerialNumber=3
[ 5489.687210] usb 5-1: Product: PMODface
[ 5489.687211] usb 5-1: Manufacturer: ApfelAudio
[ 5489.687212] usb 5-1: SerialNumber: 1234

# Check it's picked up as a sound card
$ aplay -l
...
card 1: PMODface [PMODface], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
  Subdevice #0: subdevice #0

# To test 4ch outputs on Linux you can use something like
$ speaker-test --device plughw:CARD=PMODface -c 4
```

## Porting

It should not be too hard to port this to other FPGA boards, as long as they:

- Are supported by [amaranth-boards](https://github.com/amaranth-lang/amaranth-boards/).
- [Were supported by LUNA](https://github.com/greatscottgadgets/luna-boards) (i.e. USB functionality was mapped and tested at some point)
- You will need to create your own platform file like `rtl/ecpix5.py`, add another PLL output for the audio domain and set `LUNA_PLATFORM` appropriately.

## Previous Work

This work builds on the following fantastic open-source projects:

- [LUNA](https://github.com/greatscottgadgets/luna) (Great Scott Gadgets) - open-source USB framework for FPGAs.
- [deca-usb2-audio-interface](https://github.com/amaranth-farm/deca-usb2-audio-interface) (hansfbaier@) - implementation of isochronous endpoints and most of the audio descriptor handling is lifted from here.
