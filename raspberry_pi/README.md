# Pinpoint Raspberry Pi BLE Service

Service version 0.2.0 · BLE protocol 2.0.0

This is the BLE-only Raspberry Pi half of Pinpoint. It opens no Pinpoint network port. The app can connect, arm, trigger, and receive synthetic shots or putts before the camera arrives, while Wi-Fi remains available for internet, SSH, software updates, and OpenGolfSim.

Synthetic results prove communication only. They are not measurements.

## Prepare Raspberry Pi OS

In Raspberry Pi Imager, choose **Raspberry Pi OS Lite (64-bit)**. In customization:

1. Choose any hostname and create your own username/password.
2. Configure Wi-Fi or use Ethernet so the Pi can download the initial packages.
3. Enable SSH.

Bluetooth does not require the phone and Pi to share a Wi-Fi network. A suitable Raspberry Pi 5 USB-C power supply is recommended because under-voltage can cause unreliable radio and camera behaviour.

## Copy and install the service

From PowerShell in the project directory, replace `YOUR_PI_USER` and the hostname if needed:

```powershell
scp -r .\raspberry_pi YOUR_PI_USER@launchmonitor.local:~/pinpoint-setup
ssh YOUR_PI_USER@launchmonitor.local
```

Then run on the Pi:

```bash
cd ~/pinpoint-setup
chmod +x install.sh
sudo ./install.sh
```

The installer enables BlueZ, installs the Python environment, removes the previous Pinpoint HTTP/mDNS service if present, and starts the BLE peripheral automatically at boot. Run the same installer again to update it.

## Verify the Pi

```bash
systemctl status pinpoint --no-pager
bluetoothctl show
journalctl -u pinpoint -n 50 --no-pager
```

The service log should say that `Pinpoint LM` is advertising. `bluetoothctl show` should report `Powered: yes`.

To confirm that Pinpoint no longer listens on the network:

```bash
sudo ss -lntup
```

SSH and other normal OS services may still appear, but there should be no Python process listening on port 80.

## Build the mobile app without a Mac

BLE uses native phone APIs and therefore cannot run inside Expo Go. Install a Pinpoint development build instead.

### Android from Windows

The simplest local route is Android Studio plus USB debugging:

```powershell
npm install
npm run android
```

This creates and installs the native Android app on the connected phone. No paid developer account is required.

Alternatively, use Expo's cloud build:

```powershell
npx eas-cli login
npx eas-cli build:configure
npm run build:android:dev
```

Open the build link on the Android phone and install the APK.

### iPhone from Windows

Expo's cloud can build iOS without a Mac, but Apple requires an Apple Developer account for signing and installing this custom BLE build:

```powershell
npx eas-cli login
npx eas-cli build:configure
npm run build:ios:dev
```

After installing either development build, start the JavaScript development server with `npm start` and open the Pinpoint development app.

## Connect and test

1. Keep the phone within a few metres of the Pi and enable Bluetooth.
2. Open **Device** and select **Find Pinpoint over Bluetooth**.
3. Allow the Bluetooth permission when prompted.
4. Confirm **Pi communication is working**.
5. Select **Arm**, then **Send test shot**.
6. Open Monitor and confirm a **Synthetic link test** result appears.

Wi-Fi remains connected throughout this process and can send the result to OpenGolfSim.

## Settings

Settings live in `/etc/default/pinpoint`:

```bash
PINPOINT_NAME="Pinpoint LM · Raspberry Pi"
PINPOINT_BLE_NAME="Pinpoint LM"
PINPOINT_CAPTURE_BACKEND=simulator
```

Apply changes with `sudo systemctl restart pinpoint`. Keep the short BLE name because advertising packets have limited space. Keep the simulator backend until the real camera capture module is installed.

## Main files

```text
pinpoint_ble.py          BlueZ/Bless GATT peripheral and notification framing
pinpoint_protocol.py     Commands, state, history, and synthetic capture backend
install.sh               Repeatable Raspberry Pi OS installer/updater
systemd/                 Automatic startup and restart policy
tests/                   Transport-independent BLE protocol tests
```
