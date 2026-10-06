import Ionicons from '@expo/vector-icons/Ionicons';
import React, { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Image,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ScreenHeader } from '@/components/ScreenHeader';
import { OpenGolfSimPanel } from '@/components/OpenGolfSimPanel';
import { N8nPanel } from '@/components/N8nPanel';
import { UnitsSettings } from '@/components/UnitsSettings';
import {
  CollapsibleSection,
  Eyebrow,
  HelpText,
  PrimaryButton,
  SectionHeader,
  Surface,
} from '@/components/ui';
import { useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { useN8n } from '@/context/N8nContext';
import { useOpenGolfSim } from '@/context/OpenGolfSimContext';
import { useUnits } from '@/context/UnitsContext';
import { getClub } from '@/data/clubs';
import { colors, radii, spacing } from '@/theme';
import { LightMode, WifiConnectionStatus, WifiNetwork } from '@/types';
import appConfig from '../../app.json';

const LIGHT_CHOICES: { mode: LightMode; label: string }[] = [
  { mode: 'auto', label: 'Auto' },
  { mode: 'daylight', label: 'Daylight' },
  { mode: 'flat', label: 'Flat' },
  { mode: 'strobe', label: 'Strobe' },
];

export function DeviceScreen() {
  const insets = useSafeAreaInsets();
  const {
    state,
    status,
    selectedClub,
    deviceId,
    isDemo,
    error,
    previewFrame,
    secondaryPreviewFrame,
    previewDetection,
    connect,
    disconnect,
    enableDemo,
    arm,
    disarm,
    trigger,
    setExposure,
    setGain,
    setLightMode,
    autoCalibrateExposure,
    exposureCalibration,
    clearExposureCalibration,
    getWifiStatus,
    scanWifi,
    connectWifi,
    clearError,
  } = useLaunchMonitor();
  const units = useUnits();
  const { ready: n8nReady } = useN8n();
  const { state: simState } = useOpenGolfSim();
  const [wifiStatus, setWifiStatus] = useState<WifiConnectionStatus | null>(null);
  const [wifiNetworks, setWifiNetworks] = useState<WifiNetwork[]>([]);
  const [wifiSsid, setWifiSsid] = useState('');
  const [wifiPassword, setWifiPassword] = useState('');
  const [wifiBusy, setWifiBusy] = useState<'status' | 'scan' | 'connect' | null>(null);
  const [wifiMessage, setWifiMessage] = useState<string | null>(null);
  const [wifiFailed, setWifiFailed] = useState(false);
  const [previewClock, setPreviewClock] = useState(Date.now());
  const [exposureInput, setExposureInput] = useState('');
  const [exposureBusy, setExposureBusy] = useState(false);
  const [exposureMessage, setExposureMessage] = useState<string | null>(null);
  const [exposureFailed, setExposureFailed] = useState(false);
  const [autoExposureBusy, setAutoExposureBusy] = useState(false);
  const [lightBusy, setLightBusy] = useState(false);
  const [gainInput, setGainInput] = useState('');
  const [gainBusy, setGainBusy] = useState(false);
  const [gainMessage, setGainMessage] = useState<string | null>(null);
  const [gainFailed, setGainFailed] = useState(false);
  useEffect(() => {
    if (!status?.preview) return;
    const timer = setInterval(() => setPreviewClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [status?.preview]);
  const previewFresh = Boolean(previewFrame && previewDetection &&
    previewClock - previewDetection.receivedAt < 10000 &&
    state !== 'offline' && state !== 'connecting' && state !== 'error');
  const detection = previewFresh ? previewDetection?.detection : undefined;
  const detectedBounds = detection?.state === 'detected' ? detection.bounds : null;
  const detectionLabel = !previewFresh ? 'Waiting for camera' :
    detection?.state === 'detected' ? 'Ball detected' :
    detection?.state === 'calibrating' ? 'Calibrating - keep area empty' :
    detection?.state === 'waiting' ? 'Place ball in left green zone' :
    detection?.state === 'disabled' ? 'Ball detection off' : 'Detection unavailable';

  const connected = Boolean(status);
  const setupMode = connected && !isDemo && status?.captureBackend === 'simulator';
  const connectLabel = state === 'connecting' ? 'Connecting to LM1…' : connected && !isDemo ? 'Reconnect to LM1' : 'Connect to LM1';
  const wifiProvisioning = connected && !isDemo && status?.wifiProvisioning === true;
  const selectedWifi = wifiNetworks.find((network) => network.ssid === wifiSsid);
  const exposureControl = status?.exposureControl;
  const gainControl = status?.gainControl;
  const exposureReady = Boolean(
    exposureControl?.configurable && status?.cameraConnected && !isDemo && state === 'ready' && !exposureBusy,
  );
  const isExposurePresetActive = (value: number) => Boolean(
    status && exposureControl && Math.abs(status.exposureUs - value) <= exposureControl.stepUs,
  );
  const light = status?.light;
  const strobeMode = light?.active === 'strobe' || exposureControl?.strobeMode === true;
  const lightReady = Boolean(
    light && exposureControl?.configurable && status?.cameraConnected && !isDemo &&
    state === 'ready' && !lightBusy && !exposureBusy && !autoExposureBusy,
  );
  const ringText = !light ? '' :
    light.ring === 'strobe' ? `strobing (${light.preset ?? 'driver'} pattern)` :
    light.ring === 'flat' ? 'steady' : light.ring === 'off' ? 'off' : 'unknown';
  const lightSummary = !light ? '' :
    `In use: ${light.active}${light.mode === 'auto' ? ' (chosen by auto)' : ''}. ` +
    (light.available
      ? (light.connected ? `Ring ${ringText}.` : 'Ring controller not found - plug in the ESP32.')
      : 'No ring controller set up, so a light choice only changes the shutter.');
  const exposurePresets = strobeMode ? [1000, 2000, 3000, 3900] : [20, 50, 75, 100, 150, 250];
  const gainReady = Boolean(
    gainControl?.configurable && status?.cameraConnected && !status.camera?.autoExposure &&
    !isDemo && state === 'ready' && !gainBusy,
  );
  const isGainPresetActive = (value: number) => Boolean(
    status?.camera?.gain !== undefined && gainControl &&
    Math.abs(status.camera.gain - value) <= gainControl.step,
  );

  useEffect(() => {
    if (!exposureBusy && status?.exposureUs) {
      setExposureInput(String(status.exposureUs));
    }
  }, [exposureBusy, status?.exposureUs]);

  useEffect(() => {
    if (!gainBusy && status?.camera?.gain !== undefined) {
      setGainInput(String(status.camera.gain));
    }
  }, [gainBusy, status?.camera?.gain]);

  // The device reports back over an event rather than the command response, so the
  // spinner is cleared by the result arriving, not by the request returning.
  useEffect(() => {
    if (exposureCalibration) setAutoExposureBusy(false);
  }, [exposureCalibration]);

  const handleLightChoice = async (mode: LightMode) => {
    setLightBusy(true);
    setExposureFailed(false);
    setExposureMessage(null);
    try {
      const nextStatus = await setLightMode(mode);
      setExposureInput(String(nextStatus.exposureUs));
      if (mode === 'auto') {
        // Auto means "look at the room": the same measurement as Auto-set also picks the light.
        setLightBusy(false);
        await handleAutoExposure();
      } else {
        setExposureMessage(`Light: ${mode}. Shutter ${nextStatus.exposureUs} μs - each light remembers its own shutter and boost.`);
      }
    } catch (caught) {
      setExposureFailed(true);
      setExposureMessage(caught instanceof Error ? caught.message : 'Could not change the light.');
    } finally {
      setLightBusy(false);
    }
  };

  const handleAutoExposure = async () => {
    setAutoExposureBusy(true);
    setExposureMessage(null);
    setExposureFailed(false);
    clearExposureCalibration();
    try {
      await autoCalibrateExposure();
    } catch {
      // The context already surfaces the reason in the error banner.
      setAutoExposureBusy(false);
    }
  };

  const handleExposureChange = async (requested?: number) => {
    const exposureUs = requested ?? Number(exposureInput);
    const minUs = exposureControl?.minUs ?? 50;
    const maxUs = exposureControl?.maxUs ?? 250;
    if (!Number.isInteger(exposureUs) || exposureUs < minUs || exposureUs > maxUs) {
      setExposureFailed(true);
      setExposureMessage(`Enter a whole number from ${minUs} to ${maxUs} μs.`);
      return;
    }
    setExposureInput(String(exposureUs));
    setExposureBusy(true);
    setExposureFailed(false);
    setExposureMessage(null);
    try {
      const nextStatus = await setExposure(exposureUs);
      setExposureInput(String(nextStatus.exposureUs));
      setExposureMessage(`Requested ${exposureUs} μs and saved on LM1; the camera may round to its nearest supported timing.`);
    } catch (caught) {
      setExposureFailed(true);
      setExposureMessage(caught instanceof Error ? caught.message : 'Could not change exposure.');
    } finally {
      setExposureBusy(false);
    }
  };

  const handleGainChange = async (requested?: number) => {
    const gain = requested ?? Number(gainInput);
    const min = gainControl?.min ?? 1;
    const max = gainControl?.max ?? 16;
    if (!Number.isFinite(gain) || gain < min || gain > max) {
      setGainFailed(true);
      setGainMessage(`Enter a gain from ${min} to ${max}.`);
      return;
    }
    setGainInput(String(gain));
    setGainBusy(true);
    setGainFailed(false);
    setGainMessage(null);
    try {
      const nextStatus = await setGain(gain);
      setGainInput(String(nextStatus.camera?.gain ?? gain));
      setGainMessage(`Gain ${gain.toFixed(2).replace(/\.00$/, '')}× saved on LM1.`);
    } catch (caught) {
      setGainFailed(true);
      setGainMessage(caught instanceof Error ? caught.message : 'Could not change camera gain.');
    } finally {
      setGainBusy(false);
    }
  };

  useEffect(() => {
    let cancelled = false;
    if (!wifiProvisioning) {
      setWifiStatus(null);
      setWifiNetworks([]);
      setWifiSsid('');
      setWifiPassword('');
      setWifiBusy(null);
      setWifiMessage(null);
      return () => {
        cancelled = true;
      };
    }

    setWifiBusy('status');
    void getWifiStatus()
      .then((nextStatus) => {
        if (cancelled) return;
        setWifiStatus(nextStatus);
        setWifiSsid(nextStatus.ssid ?? '');
      })
      .catch((caught: unknown) => {
        if (cancelled) return;
        setWifiFailed(true);
        setWifiMessage(caught instanceof Error ? caught.message : 'Could not read Wi-Fi status.');
      })
      .finally(() => {
        if (!cancelled) setWifiBusy(null);
      });

    return () => {
      cancelled = true;
    };
  }, [deviceId, getWifiStatus, wifiProvisioning]);

  const handleWifiScan = async () => {
    setWifiBusy('scan');
    setWifiFailed(false);
    setWifiMessage(null);
    try {
      const networks = await scanWifi();
      setWifiNetworks(networks);
      const current = networks.find((network) => network.connected);
      if (!wifiSsid && current) setWifiSsid(current.ssid);
      if (networks.length === 0) setWifiMessage('No Wi-Fi networks found. You can enter a hidden network below.');
    } catch (caught) {
      setWifiFailed(true);
      setWifiMessage(caught instanceof Error ? caught.message : 'Wi-Fi scan failed.');
    } finally {
      setWifiBusy(null);
    }
  };

  const handleWifiConnect = async () => {
    const ssid = wifiSsid.trim();
    if (!ssid) {
      setWifiFailed(true);
      setWifiMessage('Enter or select a Wi-Fi network name.');
      return;
    }
    setWifiBusy('connect');
    setWifiFailed(false);
    setWifiMessage(null);
    try {
      const nextStatus = await connectWifi(
        ssid,
        wifiPassword,
        !wifiNetworks.some((network) => network.ssid === ssid),
      );
      setWifiStatus(nextStatus);
      setWifiPassword('');
      setWifiNetworks((current) =>
        current.map((network) => ({ ...network, connected: network.ssid === ssid })),
      );
      setWifiMessage(`LM1 joined ${ssid}${nextStatus.ipAddress ? ` · ${nextStatus.ipAddress}` : ''}.`);
    } catch (caught) {
      setWifiFailed(true);
      setWifiMessage(caught instanceof Error ? caught.message : 'Could not connect LM1 to Wi-Fi.');
    } finally {
      setWifiBusy(null);
    }
  };

  const confirmDisconnect = () => {
    // The web build has no native alert dialog, so only ask where one exists.
    if (Platform.OS === 'web') {
      disconnect();
      return;
    }
    Alert.alert(
      'Disconnect your LM1?',
      'The app will stop receiving shots until you connect again.',
      [
        { text: 'Stay connected', style: 'cancel' },
        { text: 'Disconnect', style: 'destructive', onPress: disconnect },
      ],
    );
  };

  return (
    <ScrollView
      contentContainerStyle={[styles.content, { paddingTop: insets.top + spacing.md }]}
      showsVerticalScrollIndicator={false}
    >
        <ScreenHeader title="Device" subtitle="Connection & setup" state={state} demo={isDemo} />

        <Surface style={styles.connectionCard}>
          <View style={styles.connectionTitleRow}>
            <View style={[styles.deviceIcon, connected && styles.deviceIconOnline]}>
              <Ionicons
                name="hardware-chip"
                size={24}
                color={connected ? colors.accent : colors.textDim}
              />
            </View>
            <View style={styles.connectionCopy}>
              <Eyebrow>{connected ? 'Active monitor' : 'Step 1'}</Eyebrow>
              <Text style={styles.connectionTitle}>{connected ? (isDemo ? 'LM1 · Demo' : 'LM1') : 'Connect to LM1'}</Text>
              <Text style={styles.connectionSubtitle}>
                {isDemo
                  ? 'Showing sample data so you can look around'
                  : connected
                    ? 'Connected over Bluetooth · your Wi-Fi stays free'
                    : 'Turn on Bluetooth and stand near your monitor'}
              </Text>
            </View>
          </View>

          {error ? (
            <View style={styles.errorBox}>
              <Ionicons name="alert-circle" size={17} color={colors.red} />
              <Text style={styles.errorText}>{error}</Text>
              <Text accessibilityRole="button" onPress={clearError} style={styles.dismissText}>Dismiss</Text>
            </View>
          ) : null}

          {setupMode ? (
            <View style={styles.setupBanner}>
              <Ionicons name="checkmark-circle" size={19} color={colors.accent} />
              <View style={styles.setupBannerCopy}>
                <Text style={styles.setupBannerTitle}>Your monitor is talking to the app</Text>
                <Text style={styles.setupBannerBody}>You are in camera setup mode. Use the preview below to aim and focus the camera. Shot numbers are still samples until the camera is set up.</Text>
              </View>
            </View>
          ) : null}

          <PrimaryButton
            label={connectLabel}
            icon="bluetooth"
            loading={state === 'connecting'}
            onPress={() => void connect()}
          />
          <View style={styles.orRow}>
            <View style={styles.orLine} />
            <Text style={styles.orText}>NO MONITOR HANDY?</Text>
            <View style={styles.orLine} />
          </View>
          <PrimaryButton
            label="Try the demo"
            icon="play-circle"
            onPress={enableDemo}
            variant="outline"
          />
          <Text style={styles.connectionHelp}>
            The demo fills the app with sample shots so you can explore every screen. Nothing is sent
            anywhere.
          </Text>
        </Surface>

        <View style={styles.section}>
          <CollapsibleSection
            title="Units & display"
            summary="Show speeds and distances the way you think about them"
            icon="options-outline"
            badge={`${units.speedLabel} \u00b7 ${units.distanceLabel}`}
          >
            <UnitsSettings />
          </CollapsibleSection>
        </View>

        <View style={styles.section}>
          <CollapsibleSection
            title="Golf simulator"
            summary="Send your shots straight into OpenGolfSim"
            icon="game-controller-outline"
            badge={simState === 'connected' ? 'Connected' : 'Optional'}
          >
            <OpenGolfSimPanel />
          </CollapsibleSection>
        </View>

        <View style={styles.section}>
          <CollapsibleSection
            title="Automation (n8n)"
            summary="Forward shots to your own webhook"
            icon="git-network-outline"
            badge={n8nReady ? 'Set up' : 'Optional'}
          >
            <N8nPanel />
          </CollapsibleSection>
        </View>

        {status ? (
          <>
            {status.preview && !isDemo ? (
              <View style={styles.section}>
                <SectionHeader title="Camera view" />
                <Surface style={styles.previewCard}>
                  <View style={[styles.previewFrame, { aspectRatio: status.preview.width / status.preview.height }]}>
                    {previewFrame ? (
                      <Image
                        accessibilityLabel="LM1 ball placement camera preview"
                        resizeMode="cover"
                        source={{ uri: previewFrame }}
                        style={styles.previewImage}
                      />
                    ) : (
                      <View style={styles.previewLoading}>
                        <ActivityIndicator color={colors.accent} />
                        <Text style={styles.previewLoadingText}>Waiting for BLE camera frame…</Text>
                      </View>
                    )}
                    <View
                      pointerEvents="none"
                      style={[
                        styles.previewDetectionZone,
                        {
                          left: `${status.preview.roi[0] * 100}%`,
                          top: `${status.preview.roi[1] * 100}%`,
                          width: `${(status.preview.roi[2] - status.preview.roi[0]) * 100}%`,
                          height: `${(status.preview.roi[3] - status.preview.roi[1]) * 100}%`,
                        },
                      ]}
                    />
                    <View
                      pointerEvents="none"
                      style={[
                        styles.previewTarget,
                        {
                          left: `${status.preview.target[0] * 100}%`,
                          top: `${status.preview.target[1] * 100}%`,
                        },
                      ]}
                    >
                      <View style={styles.previewTargetRing} />
                    </View>
                    {detectedBounds ? (
                      <View pointerEvents="none" style={{
                        position: 'absolute', borderWidth: 3, borderColor: colors.accent,
                        left: `${detectedBounds[0] * 100}%`, top: `${detectedBounds[1] * 100}%`,
                        width: `${detectedBounds[2] * 100}%`, height: `${detectedBounds[3] * 100}%`,
                      }} />
                    ) : null}
                    <View pointerEvents="none" style={{ position: 'absolute', top: 10, left: 10, right: 10 }}>
                      <Text accessibilityLiveRegion="polite" style={{
                        alignSelf: 'flex-start', backgroundColor: '#101510', color: detection?.state === 'detected' ? colors.accent : '#FFFFFF',
                        fontWeight: '800', fontSize: 13, paddingHorizontal: 12, paddingVertical: 8, borderRadius: 8,
                      }}>{detectionLabel}</Text>
                    </View>
                  </View>
                  <View style={styles.previewMeta}>
                    <View style={styles.previewLiveDot} />
                    <Text style={styles.previewMetaText}>
                      Live preview · updates every {status.preview.intervalMs / 1000} seconds. It is small on
                      purpose: it only has to help you aim.
                    </Text>
                  </View>
                  <HelpText>The green box is the left-half placement zone. Keep the whole ball inside it; the orange ring is the preferred start. The right half stays open for left-to-right flight.</HelpText>
                  {status.camera?.model ? (
                    <View style={{ padding: spacing.md, gap: spacing.sm }}>
                      <Text style={styles.previewMetaText}>
                        {status.camera.model.toUpperCase()} · {status.camera.width}×{status.camera.height} · {status.fps} fps
                      </Text>
                      {status.camera.cameraCount === 2 ? <>
                        <Text style={styles.previewMetaText}>
                          Lower camera triggers both views · {previewFresh && status.camera.syncReady ? 'Timing matched' : 'Waiting for matched frames'}
                        </Text>
                        <Text style={styles.previewMetaText}>
                          Matched capture rate · {previewFresh ? status.camera.pairedFps ?? '…' : '…'} fps
                        </Text>
                        <Text style={styles.previewMetaText}>
                          Upper camera · {status.camera.secondaryFps ?? '…'} fps · frame offset {previewFresh ? Math.abs(status.camera.syncOffsetUs ?? 0).toFixed(0) : '…'} μs
                        </Text>
                        {secondaryPreviewFrame && previewFresh ? <Image accessibilityLabel="Upper camera live view" source={{ uri: secondaryPreviewFrame }} style={{ width: '100%', aspectRatio: 1.6 }} /> : <Text style={styles.previewMetaText}>Waiting for upper camera preview…</Text>}
                        <HelpText>The lower camera arms from the green left-half zone. Also check that the ball and its early flight stay visible in the upper camera. Exposure and brightness boost apply to both.</HelpText>
                      </> : null}
                      <Text style={styles.previewMetaText}>
                        Sharpness score: {status.camera.focusScore ?? '…'} · {status.camera.autoExposure ? 'Brightness set automatically' : 'Brightness set by hand'}
                      </Text>
                      <HelpText>
                        To focus: put a printed target where your ball will sit, inside the green box.
                        {status.camera.autofocus === false ? ' Turn the lens slowly by hand. ' : ' '}
                        Hold the camera, target and lighting still and watch the sharpness score — higher
                        is sharper.
                      </HelpText>
                    </View>
                  ) : null}
                </Surface>
              </View>
            ) : null}

            {!isDemo ? (
              <View style={styles.section}>
                <CollapsibleSection
                  title="Wi-Fi setup"
                  summary="Put your monitor online for updates"
                  icon="wifi-outline"
                  badge={wifiStatus?.connected ? 'Connected' : 'Optional'}
                >
                {wifiProvisioning ? (
                  <Surface style={styles.wifiCard}>
                    <View style={styles.wifiStatusRow}>
                      <View style={[styles.wifiIcon, wifiStatus?.connected && styles.wifiIconOnline]}>
                        <Ionicons
                          name={wifiStatus?.connected ? 'wifi' : 'wifi-outline'}
                          size={21}
                          color={wifiStatus?.connected ? colors.accent : colors.textMuted}
                        />
                      </View>
                      <View style={styles.wifiStatusCopy}>
                        <Text style={styles.wifiStatusTitle}>
                          {wifiBusy === 'status'
                            ? 'Checking Wi-Fi…'
                            : wifiStatus?.connected
                              ? wifiStatus.ssid
                              : 'Not connected'}
                        </Text>
                        <Text style={styles.wifiStatusBody}>
                          {wifiBusy === 'status'
                            ? 'Checking Raspberry Pi Wi-Fi…'
                            : wifiStatus?.ipAddress
                              ? `Pi address ${wifiStatus.ipAddress}`
                              : 'Pick a nearby network so your monitor can get updates.'}
                        </Text>
                      </View>
                    </View>

                    <PrimaryButton
                      label="Scan nearby Wi-Fi"
                      icon="search"
                      loading={wifiBusy === 'scan'}
                      disabled={wifiBusy !== null && wifiBusy !== 'scan'}
                      onPress={() => void handleWifiScan()}
                      variant="outline"
                    />

                    {wifiNetworks.length > 0 ? (
                      <View style={styles.wifiNetworkList}>
                        {wifiNetworks.map((network) => {
                          const selected = network.ssid === wifiSsid;
                          return (
                            <Pressable
                              accessibilityRole="button"
                              accessibilityLabel={`${network.ssid}, ${network.signal}% signal, ${network.security}`}
                              accessibilityState={{ selected, disabled: !network.supported }}
                              disabled={!network.supported || wifiBusy !== null}
                              key={network.ssid}
                              onPress={() => {
                                setWifiSsid(network.ssid);
                                setWifiPassword('');
                                setWifiFailed(false);
                                setWifiMessage(
                                  network.supported ? null : 'Enterprise Wi-Fi is not supported by in-app setup.',
                                );
                              }}
                              style={({ pressed }) => [
                                styles.wifiNetwork,
                                selected && styles.wifiNetworkSelected,
                                !network.supported && styles.wifiNetworkDisabled,
                                pressed && styles.wifiNetworkPressed,
                              ]}
                            >
                              <Ionicons
                                name={network.secure ? 'lock-closed-outline' : 'lock-open-outline'}
                                size={16}
                                color={selected ? colors.accent : colors.textMuted}
                              />
                              <View style={styles.wifiNetworkCopy}>
                                <Text numberOfLines={1} style={styles.wifiNetworkName}>{network.ssid}</Text>
                                <Text style={styles.wifiNetworkMeta}>
                                  {network.connected ? 'Connected · ' : ''}{network.security}{network.supported ? '' : ' · Not supported'}
                                </Text>
                              </View>
                              <Text style={styles.wifiSignal}>{network.signal}%</Text>
                            </Pressable>
                          );
                        })}
                      </View>
                    ) : null}

                    <View style={styles.wifiFields}>
                      <TextInput
                        accessibilityLabel="Wi-Fi network name"
                        autoCapitalize="none"
                        autoCorrect={false}
                        editable={wifiBusy === null}
                        onChangeText={setWifiSsid}
                        placeholder="Wi-Fi network name"
                        placeholderTextColor={colors.textDim}
                        style={styles.wifiInput}
                        value={wifiSsid}
                      />
                      <TextInput
                        accessibilityLabel="Wi-Fi password"
                        autoCapitalize="none"
                        autoCorrect={false}
                        editable={wifiBusy === null && selectedWifi?.supported !== false}
                        onChangeText={setWifiPassword}
                        onSubmitEditing={() => void handleWifiConnect()}
                        placeholder={selectedWifi?.secure === false ? 'No password needed' : 'Wi-Fi password'}
                        placeholderTextColor={colors.textDim}
                        returnKeyType="done"
                        secureTextEntry
                        style={styles.wifiInput}
                        value={wifiPassword}
                      />
                    </View>

                    <Text style={styles.wifiSecurityNote}>
                      Do this somewhere private — the Bluetooth link is not paired yet. Your password is
                      sent once and is never stored by the app.
                    </Text>
                    {wifiMessage ? (
                      <Text style={[styles.wifiMessage, wifiFailed && styles.wifiMessageError]}>{wifiMessage}</Text>
                    ) : null}
                    <PrimaryButton
                      label="Connect LM1 to Wi-Fi"
                      icon="wifi"
                      loading={wifiBusy === 'connect'}
                      disabled={
                        wifiBusy !== null ||
                        !wifiSsid.trim() ||
                        selectedWifi?.supported === false
                      }
                      onPress={() => void handleWifiConnect()}
                    />
                  </Surface>
                ) : (
                  <Surface style={styles.wifiUpdateCard}>
                    <Ionicons name="download-outline" size={20} color={colors.orange} />
                    <View style={styles.wifiStatusCopy}>
                      <Text style={styles.wifiStatusTitle}>Pi service update required</Text>
                      <Text style={styles.wifiStatusBody}>Install LM1 Pi service v0.4.0 to enable Wi-Fi setup over Bluetooth.</Text>
                    </View>
                  </Surface>
                )}
                </CollapsibleSection>
              </View>
            ) : null}

            <View style={styles.section}>
              <SectionHeader title="System health" />
              <View style={styles.healthGrid}>
                <HealthTile icon="bluetooth" label="Bluetooth" value="Connected" healthy />
                <HealthTile icon="videocam" label="Camera" value={status.cameraConnected ? 'Working' : 'Not fitted'} healthy={status.cameraConnected} />
                <HealthTile icon="speedometer" label="Capture speed" value={setupMode ? 'Test mode' : `${status.fps} fps`} healthy={setupMode || status.fps >= 280} />
                <HealthTile icon="thermometer" label="Temperature" value={`${status.temperatureC.toFixed(0)} °C`} healthy={status.temperatureC < 75} />
              </View>
            </View>

            <View style={styles.section}>
              <SectionHeader title="Monitor" />
              <Surface style={styles.controlCard}>
                <InfoRow icon="radio-outline" label="Right now" value={stateLabel(state)} valueColor={state === 'armed' ? colors.cyan : colors.accent} />
                <InfoRow icon="golf-outline" label="Selected club" value={getClub(selectedClub).label} />
                <InfoRow icon="albums-outline" label="Free storage" value={`${status.storageFreeGb.toFixed(1)} GB`} />
                <InfoRow icon="git-branch-outline" label="Software version" value={`v${status.firmwareVersion}`} />
                <View style={styles.actionRow}>
                  <View style={styles.actionButton}>
                    <PrimaryButton
                      label={state === 'armed' ? 'Stop tracking' : 'Start tracking'}
                      icon={state === 'armed' ? 'stop-circle' : 'radio'}
                      onPress={() => void (state === 'armed' ? disarm() : arm())}
                      variant="dark"
                      disabled={state === 'processing'}
                    />
                  </View>
                  <View style={styles.actionButton}>
                    <PrimaryButton
                      label={isDemo ? 'Demo shot' : setupMode ? 'Send test shot' : 'Record a shot'}
                      icon="flash"
                      onPress={() => void trigger()}
                      variant="outline"
                      disabled={state === 'processing'}
                    />
                  </View>
                </View>
              </Surface>
            </View>

            <View style={styles.section}>
              <CollapsibleSection
                title="Camera tuning"
                summary="Brightness and motion blur — only if shots are not reading well"
                icon="construct-outline"
                badge={status.cameraConnected ? `${status.exposureUs} μs` : 'No camera'}
              >
              <View style={styles.tuningCard}>
                <HelpText>
                  The defaults suit most rooms. Change these only if the camera view looks too dark,
                  too bright, or smeared.
                </HelpText>
                <InfoRow icon="flash-outline" label="Shutter" value={status.cameraConnected ? `${status.exposureUs} μs` : 'Waiting for camera'} />
                <InfoRow icon="options-outline" label="Brightness boost" value={status.camera?.gain !== undefined ? `${status.camera.gain.toFixed(2).replace(/\.00$/, '')}×` : 'Waiting for camera'} />

                <View style={styles.autoExposureBlock}>
                  <Text style={styles.exposureTitle}>Set it for me</Text>
                  <Text style={styles.exposureHelp}>
                    LM1 tries a range of shutter speeds, looks at how bright each one comes out, and
                    keeps the fastest one that still sees the ball clearly. Takes a few seconds.
                  </Text>
                  <PrimaryButton
                    label={autoExposureBusy ? 'Measuring the light…' : 'Auto-set for this room'}
                    icon="sparkles"
                    loading={autoExposureBusy}
                    disabled={!exposureReady || autoExposureBusy}
                    onPress={() => void handleAutoExposure()}
                  />
                  {!exposureReady && !autoExposureBusy ? (
                    <Text style={styles.exposureHelp}>
                      {status.cameraConnected
                        ? 'Stop tracking first, then try again.'
                        : 'Connect a camera to use automatic exposure.'}
                    </Text>
                  ) : null}
                  {exposureCalibration ? (
                    <View style={[
                      styles.autoExposureResult,
                      !exposureCalibration.ok || exposureCalibration.usable === false
                        ? styles.autoExposureResultWarn
                        : null,
                    ]}>
                      <Ionicons
                        name={exposureCalibration.ok && exposureCalibration.usable !== false
                          ? 'checkmark-circle'
                          : 'alert-circle'}
                        size={17}
                        color={exposureCalibration.ok && exposureCalibration.usable !== false
                          ? colors.accent
                          : colors.orange}
                      />
                      <View style={styles.autoExposureResultCopy}>
                        <Text style={styles.autoExposureResultTitle}>
                          {exposureCalibration.ok
                            ? `Set to ${exposureCalibration.exposureUs} μs at ${exposureCalibration.gain?.toFixed(2).replace(/\.00$/, '')}×${exposureCalibration.light ? ` - ${exposureCalibration.light === 'daylight' ? 'daylight, ring off' : 'steady ring'}` : ''}`
                            : 'Automatic exposure did not finish'}
                        </Text>
                        <Text style={styles.autoExposureResultBody}>
                          {exposureCalibration.ok
                            ? exposureCalibration.note
                            : exposureCalibration.error}
                        </Text>
                      </View>
                    </View>
                  ) : null}
                  <Text style={styles.exposureHelp}>
                    You can still set everything by hand below — automatic just gives you a
                    starting point.
                  </Text>
                </View>

                {light ? (
                  <View style={styles.exposureControl}>
                    <View style={styles.exposureHeading}>
                      <View style={styles.strobeText}>
                        <Text style={styles.exposureTitle}>Light</Text>
                        <Text style={styles.exposureHelp}>
                          Auto picks the light for the room. Daylight turns the ring off and uses the sun
                          (outdoors). Flat keeps the ring steady (indoors). Strobe flashes the ring for a
                          dark room and is a test mode: captures are saved but not measured.
                        </Text>
                      </View>
                    </View>
                    <View style={styles.exposurePresets}>
                      {LIGHT_CHOICES.map((choice) => {
                        const selected = light.mode === choice.mode;
                        return (
                          <Pressable
                            accessibilityRole="button"
                            accessibilityLabel={`Light: ${choice.label}`}
                            accessibilityState={{ selected }}
                            disabled={!lightReady}
                            key={choice.mode}
                            onPress={() => void handleLightChoice(choice.mode)}
                            style={({ pressed }) => [
                              styles.exposurePreset,
                              selected && styles.exposurePresetActive,
                              !lightReady && styles.exposurePresetDisabled,
                              pressed && styles.wifiNetworkPressed,
                            ]}
                          >
                            <Text style={[styles.exposurePresetText, selected && styles.exposurePresetTextActive]}>
                              {choice.label}
                            </Text>
                          </Pressable>
                        );
                      })}
                    </View>
                    <Text style={styles.exposureHelp}>{lightSummary}</Text>
                    {state !== 'ready' && exposureControl?.configurable ? (
                      <Text style={styles.exposureHelp}>Stop tracking before changing the light.</Text>
                    ) : null}
                  </View>
                ) : null}
                {exposureControl ? (
                  <View style={styles.exposureControl}>
                    <View style={styles.exposureHeading}>
                      <View>
                        <Text style={styles.exposureTitle}>Shutter speed</Text>
                        <Text style={styles.exposureHelp}>
                          {exposureControl.minUs}–{exposureControl.maxUs} μs. Lower freezes the ball more
                          sharply; higher gives a brighter picture. The sensor may round to its nearest
                          setting.
                        </Text>
                      </View>
                    </View>
                    <View style={styles.exposureInputRow}>
                      <TextInput
                        accessibilityLabel="Camera exposure in microseconds"
                        editable={exposureReady}
                        keyboardType="number-pad"
                        maxLength={4}
                        onChangeText={(value) => {
                          setExposureInput(value.replace(/[^0-9]/g, ''));
                          setExposureMessage(null);
                        }}
                        onSubmitEditing={() => void handleExposureChange()}
                        placeholder="191"
                        placeholderTextColor={colors.textDim}
                        returnKeyType="done"
                        selectTextOnFocus
                        style={styles.exposureInput}
                        value={exposureInput}
                      />
                      <Text style={styles.exposureUnit}>μs</Text>
                      <View style={styles.exposureApply}>
                        <PrimaryButton
                          label="Apply"
                          loading={exposureBusy}
                          disabled={!exposureReady || !exposureInput}
                          onPress={() => void handleExposureChange()}
                          variant="outline"
                        />
                      </View>
                    </View>
                    <View style={styles.exposurePresets}>
                      {exposurePresets.map((value) => (
                        <Pressable
                          accessibilityRole="button"
                          accessibilityLabel={`Set exposure to ${value} microseconds`}
                          disabled={!exposureReady}
                          key={value}
                          onPress={() => void handleExposureChange(value)}
                          style={({ pressed }) => [
                            styles.exposurePreset,
                            isExposurePresetActive(value) && styles.exposurePresetActive,
                            !exposureReady && styles.exposurePresetDisabled,
                            pressed && styles.wifiNetworkPressed,
                          ]}
                        >
                          <Text style={[
                            styles.exposurePresetText,
                            isExposurePresetActive(value) && styles.exposurePresetTextActive,
                          ]}>{value}</Text>
                        </Pressable>
                      ))}
                    </View>
                    {state !== 'ready' && exposureControl.configurable ? (
                      <Text style={styles.exposureHelp}>Stop tracking before changing the shutter speed.</Text>
                    ) : null}
                    {exposureMessage ? (
                      <Text style={[styles.exposureMessage, exposureFailed && styles.exposureMessageError]}>
                        {exposureMessage}
                      </Text>
                    ) : null}
                  </View>
                ) : null}
                {gainControl ? (
                  <View style={styles.exposureControl}>
                    <View style={styles.exposureHeading}>
                      <View>
                        <Text style={styles.exposureTitle}>Brightness boost</Text>
                        <Text style={styles.exposureHelp}>
                          {gainControl.min}–{gainControl.max}×. Higher brightens a dark picture but makes it
                          grainier. Try a slower shutter first.
                        </Text>
                      </View>
                    </View>
                    <View style={styles.exposureInputRow}>
                      <TextInput
                        accessibilityLabel="Camera analogue gain"
                        editable={gainReady}
                        keyboardType="decimal-pad"
                        maxLength={5}
                        onChangeText={(value) => {
                          const cleaned = value.replace(/[^0-9.]/g, '');
                          setGainInput(cleaned.indexOf('.') === cleaned.lastIndexOf('.') ? cleaned : gainInput);
                          setGainMessage(null);
                        }}
                        onSubmitEditing={() => void handleGainChange()}
                        placeholder="1"
                        placeholderTextColor={colors.textDim}
                        returnKeyType="done"
                        selectTextOnFocus
                        style={styles.exposureInput}
                        value={gainInput}
                      />
                      <Text style={styles.exposureUnit}>×</Text>
                      <View style={styles.exposureApply}>
                        <PrimaryButton
                          label="Apply"
                          loading={gainBusy}
                          disabled={!gainReady || !gainInput}
                          onPress={() => void handleGainChange()}
                          variant="outline"
                        />
                      </View>
                    </View>
                    <View style={styles.exposurePresets}>
                      {[1, 2, 4, 8, 16].map((value) => (
                        <Pressable
                          accessibilityRole="button"
                          accessibilityLabel={`Set camera gain to ${value}`}
                          disabled={!gainReady}
                          key={value}
                          onPress={() => void handleGainChange(value)}
                          style={({ pressed }) => [
                            styles.exposurePreset,
                            isGainPresetActive(value) && styles.exposurePresetActive,
                            !gainReady && styles.exposurePresetDisabled,
                            pressed && styles.wifiNetworkPressed,
                          ]}
                        >
                          <Text style={[
                            styles.exposurePresetText,
                            isGainPresetActive(value) && styles.exposurePresetTextActive,
                          ]}>{value}×</Text>
                        </Pressable>
                      ))}
                    </View>
                    {status.camera?.autoExposure ? (
                      <Text style={styles.exposureHelp}>Set a shutter speed by hand before changing this.</Text>
                    ) : state !== 'ready' && gainControl.configurable ? (
                      <Text style={styles.exposureHelp}>Stop tracking before changing the brightness boost.</Text>
                    ) : null}
                    {gainMessage ? (
                      <Text style={[styles.exposureMessage, gainFailed && styles.exposureMessageError]}>
                        {gainMessage}
                      </Text>
                    ) : null}
                  </View>
                ) : null}
              </View>
              </CollapsibleSection>
            </View>

            {!isDemo ? (
              <View style={styles.disconnectButton}>
                <PrimaryButton
                  label="Disconnect monitor"
                  icon="unlink"
                  onPress={confirmDisconnect}
                  variant="danger"
                />
                <Text style={styles.disconnectHelp}>
                  You can reconnect at any time. Shots already in this session stay in Sessions.
                </Text>
              </View>
            ) : null}
          </>
        ) : (
          <Surface style={styles.tipCard}>
            <View style={styles.tipIcon}>
              <Ionicons name="bluetooth" size={20} color={colors.cyan} />
            </View>
            <View style={styles.tipCopy}>
              <Text style={styles.tipTitle}>Connecting takes Bluetooth only</Text>
              <Text style={styles.tipBody}>
                Turn Bluetooth on and stand within a few metres of the monitor. Your Wi‑Fi stays free
                for your simulator and the internet.
              </Text>
            </View>
          </Surface>
        )}

      <Text style={styles.version}>LM1 MOBILE · VERSION {appConfig.expo.version}</Text>
    </ScrollView>
  );
}

function HealthTile({
  icon,
  label,
  value,
  healthy,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  value: string;
  healthy: boolean;
}) {
  return (
    <Surface style={styles.healthTile}>
      <View style={styles.healthTop}>
        <Ionicons name={icon} size={17} color={colors.textMuted} />
        <View style={[styles.healthDot, { backgroundColor: healthy ? colors.accent : colors.orange }]} />
      </View>
      <Text style={styles.healthValue}>{value}</Text>
      <Text style={styles.healthLabel}>{label}</Text>
    </Surface>
  );
}

function InfoRow({
  icon,
  label,
  value,
  valueColor,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  label: string;
  value: string;
  valueColor?: string;
}) {
  return (
    <View style={styles.infoRow}>
      <View style={styles.infoLabelRow}>
        <Ionicons name={icon} size={17} color={colors.textMuted} />
        <Text style={styles.infoLabel}>{label}</Text>
      </View>
      <Text style={[styles.infoValue, valueColor ? { color: valueColor } : null]}>{value}</Text>
    </View>
  );
}

function stateLabel(state: string): string {
  return state.charAt(0).toUpperCase() + state.slice(1);
}

const styles = StyleSheet.create({
  content: { paddingBottom: 110, paddingHorizontal: spacing.md },
  connectionCard: { padding: spacing.lg },
  connectionTitleRow: { alignItems: 'center', flexDirection: 'row', marginBottom: spacing.lg },
  deviceIcon: { alignItems: 'center', backgroundColor: colors.surfaceRaised, borderRadius: 20, height: 52, justifyContent: 'center', marginRight: 13, width: 52 },
  deviceIconOnline: { backgroundColor: '#192219' },
  connectionCopy: { flex: 1 },
  connectionTitle: { color: colors.text, fontSize: 18, fontWeight: '700', marginTop: 3 },
  connectionSubtitle: { color: colors.textMuted, fontSize: 12, fontWeight: '600', lineHeight: 16, marginTop: 3 },
  connectionHelp: { color: colors.textMuted, fontSize: 12, lineHeight: 17, marginTop: spacing.sm },
  errorBox: { alignItems: 'center', backgroundColor: '#241718', borderRadius: radii.sm, flexDirection: 'row', gap: 8, marginBottom: spacing.md, padding: 11 },
  errorText: { color: '#F0B0AC', flex: 1, fontSize: 12, lineHeight: 17 },
  dismissText: { color: colors.text, fontSize: 12, fontWeight: '800' },
  setupBanner: { alignItems: 'flex-start', backgroundColor: '#17231A', borderColor: '#344E32', borderRadius: radii.md, borderWidth: 1, flexDirection: 'row', gap: 10, marginBottom: spacing.md, padding: 12 },
  setupBannerCopy: { flex: 1 },
  setupBannerTitle: { color: colors.accent, fontSize: 13, fontWeight: '800' },
  setupBannerBody: { color: colors.textMuted, fontSize: 12, lineHeight: 17, marginTop: 3 },
  orRow: { alignItems: 'center', flexDirection: 'row', gap: 10, marginVertical: spacing.md },
  orLine: { backgroundColor: colors.line, flex: 1, height: 1 },
  orText: { color: colors.textDim, fontSize: 10, fontWeight: '800', letterSpacing: 0.7 },
  section: { marginTop: spacing.xl },
  previewCard: { overflow: 'hidden' },
  previewFrame: { aspectRatio: 4 / 3, backgroundColor: colors.surfaceRaised, position: 'relative', width: '100%' },
  previewImage: { height: '100%', width: '100%' },
  previewLoading: { alignItems: 'center', gap: spacing.sm, height: '100%', justifyContent: 'center', width: '100%' },
  previewLoadingText: { color: colors.textMuted, fontSize: 11, fontWeight: '600' },
  previewDetectionZone: { borderColor: colors.accent, borderStyle: 'dashed', borderWidth: 2, position: 'absolute' },
  previewTarget: { alignItems: 'center', height: 44, justifyContent: 'center', marginLeft: -22, marginTop: -22, position: 'absolute', width: 44 },
  previewTargetRing: { borderColor: colors.orange, borderRadius: 22, borderWidth: 3, height: 44, width: 44 },
  previewMeta: { alignItems: 'center', flexDirection: 'row', gap: spacing.sm, padding: spacing.md },
  previewLiveDot: { backgroundColor: colors.accent, borderRadius: 4, height: 7, width: 7 },
  previewMetaText: { color: colors.textMuted, flex: 1, fontSize: 12, fontWeight: '700', lineHeight: 16 },
  wifiCard: { gap: spacing.md, padding: spacing.lg },
  wifiStatusRow: { alignItems: 'center', flexDirection: 'row' },
  wifiIcon: { alignItems: 'center', backgroundColor: colors.surfaceRaised, borderRadius: 17, height: 44, justifyContent: 'center', marginRight: 11, width: 44 },
  wifiIconOnline: { backgroundColor: '#192219' },
  wifiStatusCopy: { flex: 1 },
  wifiStatusTitle: { color: colors.text, fontSize: 14, fontWeight: '800' },
  wifiStatusBody: { color: colors.textMuted, fontSize: 12, lineHeight: 17, marginTop: 3 },
  wifiNetworkList: { borderColor: colors.line, borderRadius: radii.md, borderWidth: 1, overflow: 'hidden' },
  wifiNetwork: { alignItems: 'center', borderBottomColor: colors.line, borderBottomWidth: 1, flexDirection: 'row', minHeight: 52, paddingHorizontal: 12 },
  wifiNetworkSelected: { backgroundColor: '#192219' },
  wifiNetworkDisabled: { opacity: 0.45 },
  wifiNetworkPressed: { opacity: 0.75 },
  wifiNetworkCopy: { flex: 1, marginHorizontal: 10 },
  wifiNetworkName: { color: colors.text, fontSize: 14, fontWeight: '700' },
  wifiNetworkMeta: { color: colors.textMuted, fontSize: 11, marginTop: 2 },
  wifiSignal: { color: colors.textMuted, fontSize: 12, fontWeight: '800' },
  wifiFields: { gap: spacing.sm },
  wifiInput: { backgroundColor: colors.surfaceRaised, borderColor: colors.lineStrong, borderRadius: radii.md, borderWidth: 1, color: colors.text, fontSize: 14, minHeight: 52, paddingHorizontal: spacing.md },
  wifiSecurityNote: { color: colors.textMuted, fontSize: 11, lineHeight: 16 },
  wifiMessage: { color: colors.accent, fontSize: 12, fontWeight: '700', lineHeight: 17 },
  wifiMessageError: { color: colors.red },
  wifiUpdateCard: { alignItems: 'center', flexDirection: 'row', gap: spacing.sm, padding: spacing.md },
  healthGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  healthTile: { minHeight: 112, padding: spacing.md, width: '48.5%' },
  healthTop: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between' },
  healthDot: { borderRadius: 4, height: 7, width: 7 },
  healthValue: { color: colors.text, fontSize: 22, fontWeight: '700', marginTop: spacing.md },
  healthLabel: { color: colors.textMuted, fontSize: 12, fontWeight: '700', marginTop: 2 },
  controlCard: { padding: spacing.lg },
  infoRow: { alignItems: 'center', borderBottomColor: colors.line, borderBottomWidth: 1, flexDirection: 'row', justifyContent: 'space-between', minHeight: 46 },
  infoLabelRow: { alignItems: 'center', flexDirection: 'row', gap: 9 },
  infoLabel: { color: colors.textMuted, fontSize: 13, fontWeight: '600' },
  infoValue: { color: colors.text, fontSize: 13, fontWeight: '800' },
  tuningCard: { gap: spacing.sm },
  autoExposureBlock: {
    borderBottomColor: colors.line,
    borderBottomWidth: 1,
    gap: spacing.sm,
    paddingVertical: spacing.md,
  },
  autoExposureResult: {
    alignItems: 'flex-start',
    backgroundColor: '#17231A',
    borderColor: '#344E32',
    borderRadius: radii.md,
    borderWidth: 1,
    flexDirection: 'row',
    gap: spacing.sm,
    padding: spacing.sm,
  },
  autoExposureResultWarn: { backgroundColor: '#241E17', borderColor: '#4E4032' },
  autoExposureResultCopy: { flex: 1 },
  autoExposureResultTitle: { color: colors.text, fontSize: 13, fontWeight: '800' },
  autoExposureResultBody: { color: colors.textMuted, fontSize: 12, lineHeight: 16, marginTop: 2 },
  exposureControl: { borderBottomColor: colors.line, borderBottomWidth: 1, gap: spacing.sm, paddingVertical: spacing.md },
  exposureHeading: { flexDirection: 'row', justifyContent: 'space-between' },
  strobeText: { flex: 1, paddingRight: spacing.md },
  exposureTitle: { color: colors.text, fontSize: 14, fontWeight: '800' },
  exposureHelp: { color: colors.textMuted, fontSize: 12, lineHeight: 16, marginTop: 3 },
  exposureInputRow: { alignItems: 'center', flexDirection: 'row', gap: spacing.sm },
  exposureInput: { backgroundColor: colors.surfaceRaised, borderColor: colors.lineStrong, borderRadius: radii.md, borderWidth: 1, color: colors.text, fontSize: 17, fontWeight: '800', minHeight: 54, paddingHorizontal: spacing.md, textAlign: 'right', width: 86 },
  exposureUnit: { color: colors.textMuted, fontSize: 12, fontWeight: '700' },
  exposureApply: { flex: 1 },
  exposurePresets: { flexDirection: 'row', gap: spacing.sm },
  exposurePreset: { alignItems: 'center', backgroundColor: colors.surfaceRaised, borderColor: colors.lineStrong, borderRadius: radii.pill, borderWidth: 1, flex: 1, justifyContent: 'center', minHeight: 36 },
  exposurePresetActive: { backgroundColor: '#192219', borderColor: colors.accent },
  exposurePresetDisabled: { opacity: 0.45 },
  exposurePresetText: { color: colors.textMuted, fontSize: 12, fontWeight: '800' },
  exposurePresetTextActive: { color: colors.accent },
  exposureMessage: { color: colors.accent, fontSize: 12, fontWeight: '700', lineHeight: 16 },
  exposureMessageError: { color: colors.red },
  actionRow: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.lg },
  actionButton: { flex: 1 },
  disconnectButton: { gap: spacing.sm, marginTop: spacing.xl },
  disconnectHelp: { color: colors.textMuted, fontSize: 12, lineHeight: 16, textAlign: 'center' },
  tipCard: { alignItems: 'flex-start', flexDirection: 'row', marginTop: spacing.md, padding: spacing.md },
  tipIcon: { alignItems: 'center', backgroundColor: '#142322', borderRadius: 16, height: 40, justifyContent: 'center', marginRight: 11, width: 40 },
  tipCopy: { flex: 1 },
  tipTitle: { color: colors.text, fontSize: 14, fontWeight: '700' },
  tipBody: { color: colors.textMuted, fontSize: 12, lineHeight: 17, marginTop: 4 },
  version: { color: colors.textDim, fontSize: 11, fontWeight: '800', letterSpacing: 1.2, marginTop: spacing.xl, textAlign: 'center' },
});
