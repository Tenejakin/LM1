# OpenGolfSim connection

Pinpoint supports OpenGolfSim Desktop and the experimental OpenGolfSim Web simulator from the native Pinpoint development build.

## Desktop

OpenGolfSim Desktop accepts newline-delimited JSON over TCP port `3111`. React Native cannot create raw TCP sockets without another native module, so the included bridge exposes a local WebSocket on port `3112` and forwards messages to the official API.

1. Start OpenGolfSim Desktop on the computer.
2. In this project folder on that computer, run:

```powershell
npm install
npm run ogs:bridge
```

3. Find the computer's local IPv4 address with `ipconfig`.
4. In Pinpoint, open **Device → Simulator connection → Desktop**.
5. Enter the computer address, for example `192.168.1.50:3112`, and connect.
6. Allow Node.js through the private-network firewall if Windows asks.

The bridge connects to `127.0.0.1:3111` by default. To use another OpenGolfSim host or ports:

```powershell
npm run ogs:bridge -- --ogs-host=192.168.1.60 --ogs-port=3111 --listen-port=3112
```

The bridge binds to the LAN by default. Use it only on a trusted private network, and close the terminal when the session ends.

## Web simulator

1. Open the Web simulator from the OpenGolfSim account dashboard.
2. In Pinpoint, choose **Device → Simulator connection → Web**.
3. Enter the same OpenGolfSim account email and connect.

This mode connects directly to OpenGolfSim's official secure WebSocket endpoint and does not require the desktop bridge.

## Shot data

Pinpoint sends metric payloads containing ball speed, vertical launch angle, horizontal launch angle, spin speed, and spin axis. Measured spin is preferred. Until the launch monitor reports spin, Pinpoint supplies a club-based spin estimate and a neutral spin axis so OpenGolfSim receives a complete shot.

Enable **Automatically send shots** to forward every completed device shot, demo shot, or putt. Manual calculator results can be sent with the **Send shot** button. Use **Send test shot** on the Device page to verify the connection before hitting a ball.
