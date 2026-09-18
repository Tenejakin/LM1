# LM1 Mobile App — AI Design Brief

Brief version 1.0.0

Create an original mobile interface design for **LM1**, a portable golf launch monitor. Do not inspect, reproduce, or describe any existing LM1 interface. Develop a fresh visual direction from the product requirements below.

LM1 connects a phone to a Raspberry Pi camera device over Bluetooth. Golfers use it beside a hitting mat, often outdoors or in dim simulator rooms. The interface must be readable at a glance, usable with one hand, and clear in bright and dark conditions.

Design these main areas:

- **Launch monitor:** connection state, selected club, arm/disarm control, processing feedback, ball speed, club speed, smash factor, launch angle, start direction, carry estimate, trajectory, and strike location.
- **Putting:** putter speed, ball speed, direction, launch angle, skid, roll, target pace, and green-speed context.
- **Calculator:** manual measurement entry with immediate calculated results and clear validation.
- **Sessions:** shot history, sorting, session averages, consistency, and an easy way to inspect one shot.
- **Device:** Bluetooth connection, camera preview, ball-placement area, camera calibration, focus/sharpness feedback, exposure, frame rate, storage, temperature, Wi-Fi setup, and simulator connection.

The camera preview needs four unmistakable states: **Calibrating — keep area empty**, **Waiting for ball**, **Ball detected**, and **Detection off**. When a ball is detected, show its location directly on the image with a clear bounding marker. Keep status text readable over both bright and dark camera frames. Also communicate stale or disconnected camera data instead of leaving an old detection visible.

Prioritize the live shot workflow: connect, select a club, position the ball, confirm detection, arm, capture, process, and review the result. Distinguish real measurements from synthetic test results. Use plain language, large touch targets, strong contrast, accessible type sizes, and more than color alone to convey status.

Deliver:

1. A compact visual system covering color, typography, spacing, icons, controls, cards, charts, and status treatments.
2. High-fidelity mobile screens for the five main areas and all launch-monitor states.
3. Camera-preview states, including detected-ball annotation and focus guidance.
4. Reusable component specifications and responsive behavior for common phone sizes.
5. A clickable prototype of the primary shot flow.

Keep technical implementation details out of the golfer-facing interface unless they help diagnose or configure the device. The result should feel precise, fast, trustworthy, and suitable for repeated use during practice.
