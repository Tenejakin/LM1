import Ionicons from '@expo/vector-icons/Ionicons';
import React from 'react';
import {
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { ScreenHeader } from '@/components/ScreenHeader';
import { OpenGolfSimPanel } from '@/components/OpenGolfSimPanel';
import { Eyebrow, PrimaryButton, SectionHeader, Surface } from '@/components/ui';
import { useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { getClub } from '@/data/clubs';
import { colors, radii, spacing } from '@/theme';

export function DeviceScreen() {
  const insets = useSafeAreaInsets();
  const {
    state,
    status,
    selectedClub,
    isDemo,
    error,
    connect,
    disconnect,
    enableDemo,
    arm,
    disarm,
    trigger,
    clearError,
  } = useLaunchMonitor();

  const connected = Boolean(status);
  const setupMode = connected && !isDemo && status?.captureBackend === 'simulator';
  const connectLabel = state === 'connecting' ? 'Finding Pinpoint…' : connected && !isDemo ? 'Reconnect Bluetooth' : 'Find Pinpoint over Bluetooth';

  return (
    <ScrollView
      contentContainerStyle={[styles.content, { paddingTop: insets.top + spacing.md }]}
      showsVerticalScrollIndicator={false}
    >
        <ScreenHeader title="Device" subtitle="Connection & diagnostics" state={state} demo={isDemo} />

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
              <Eyebrow>{connected ? 'Active monitor' : 'Bluetooth Low Energy'}</Eyebrow>
              <Text style={styles.connectionTitle}>{status?.name ?? 'Connect to Pinpoint'}</Text>
              <Text style={styles.connectionSubtitle}>
                {isDemo
                  ? 'Running with sample device data'
                  : connected
                    ? 'Connected over Bluetooth · Wi-Fi remains available'
                    : 'Discover the nearby Raspberry Pi without using Wi-Fi'}
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
                <Text style={styles.setupBannerTitle}>Pi communication is working</Text>
                <Text style={styles.setupBannerBody}>Camera-free BLE test mode is active. Arm and send a test shot to verify live events.</Text>
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
            <Text style={styles.orText}>OR PREVIEW WITHOUT HARDWARE</Text>
            <View style={styles.orLine} />
          </View>
          <PrimaryButton
            label="Use interactive demo"
            icon="play-circle"
            onPress={enableDemo}
            variant="outline"
          />
        </Surface>

        <View style={styles.section}>
          <SectionHeader title="Simulator connection" />
          <OpenGolfSimPanel />
        </View>

        {status ? (
          <>
            <View style={styles.section}>
              <SectionHeader title="System health" />
              <View style={styles.healthGrid}>
                <HealthTile icon="bluetooth" label="BLE link" value="Online" healthy />
                <HealthTile icon="videocam" label="Camera" value={status.cameraConnected ? 'Online' : 'Not fitted'} healthy={status.cameraConnected} />
                <HealthTile icon="speedometer" label="Capture" value={setupMode ? 'Test mode' : `${status.fps} FPS`} healthy={setupMode || status.fps >= 280} />
                <HealthTile icon="thermometer" label="Pi temp" value={`${status.temperatureC.toFixed(0)} °C`} healthy={status.temperatureC < 75} />
              </View>
            </View>

            <View style={styles.section}>
              <SectionHeader title="Capture controls" />
              <Surface style={styles.controlCard}>
                <InfoRow icon="radio-outline" label="Monitor state" value={stateLabel(state)} valueColor={state === 'armed' ? colors.cyan : colors.accent} />
                <InfoRow icon="golf-outline" label="Selected club" value={getClub(selectedClub).label} />
                <InfoRow icon="albums-outline" label="Free storage" value={`${status.storageFreeGb.toFixed(1)} GB`} />
                <InfoRow icon="flash-outline" label="Exposure" value={status.cameraConnected ? `${status.exposureUs} μs` : 'Waiting for camera'} />
                <InfoRow icon="git-branch-outline" label="Firmware" value={`v${status.firmwareVersion}`} />
                <View style={styles.actionRow}>
                  <View style={styles.actionButton}>
                    <PrimaryButton
                      label={state === 'armed' ? 'Disarm' : 'Arm'}
                      icon={state === 'armed' ? 'stop-circle' : 'radio'}
                      onPress={() => void (state === 'armed' ? disarm() : arm())}
                      variant="dark"
                      disabled={state === 'processing'}
                    />
                  </View>
                  <View style={styles.actionButton}>
                    <PrimaryButton
                      label={isDemo ? 'Demo shot' : setupMode ? 'Send test shot' : 'Test trigger'}
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
              <SectionHeader title="Calibration" />
              <Surface style={styles.calibrationCard}>
                <View style={styles.calibrationIcon}>
                  <Ionicons name={setupMode ? 'time-outline' : 'scan'} size={24} color={setupMode ? colors.orange : colors.accent} />
                </View>
                <View style={styles.calibrationCopy}>
                  <Text style={styles.calibrationTitle}>{setupMode ? 'Camera setup pending' : 'Installation geometry'}</Text>
                  <Text style={styles.calibrationBody}>
                    {setupMode
                      ? 'The Pi link is ready. Calibration becomes available after the camera is installed.'
                      : `Profile ${status.calibrationVersion} · floor, ball origin, target line and camera pose saved.`}
                  </Text>
                </View>
                <Ionicons name={setupMode ? 'ellipse-outline' : 'checkmark-circle'} size={21} color={setupMode ? colors.orange : colors.accent} />
              </Surface>
            </View>

            {!isDemo ? (
              <View style={styles.disconnectButton}>
                <PrimaryButton label="Disconnect monitor" icon="unlink" onPress={disconnect} variant="danger" />
              </View>
            ) : null}
          </>
        ) : (
          <Surface style={styles.tipCard}>
            <View style={styles.tipIcon}>
              <Ionicons name="bluetooth" size={20} color={colors.cyan} />
            </View>
            <View style={styles.tipCopy}>
              <Text style={styles.tipTitle}>Bluetooth only</Text>
              <Text style={styles.tipBody}>
                Turn on Bluetooth and stay near the Raspberry Pi. Your Wi‑Fi connection remains free for OpenGolfSim and internet data.
              </Text>
            </View>
          </Surface>
        )}

      <Text style={styles.version}>PINPOINT MOBILE · VERSION 2.0.0</Text>
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
  connectionSubtitle: { color: colors.textMuted, fontSize: 11, fontWeight: '600', marginTop: 3 },
  errorBox: { alignItems: 'center', backgroundColor: '#241718', borderRadius: radii.sm, flexDirection: 'row', gap: 8, marginBottom: spacing.md, padding: 11 },
  errorText: { color: '#F0B0AC', flex: 1, fontSize: 11, lineHeight: 16 },
  dismissText: { color: colors.text, fontSize: 10, fontWeight: '800' },
  setupBanner: { alignItems: 'flex-start', backgroundColor: '#17231A', borderColor: '#344E32', borderRadius: radii.md, borderWidth: 1, flexDirection: 'row', gap: 10, marginBottom: spacing.md, padding: 12 },
  setupBannerCopy: { flex: 1 },
  setupBannerTitle: { color: colors.accent, fontSize: 12, fontWeight: '800' },
  setupBannerBody: { color: colors.textMuted, fontSize: 10, lineHeight: 15, marginTop: 3 },
  orRow: { alignItems: 'center', flexDirection: 'row', gap: 10, marginVertical: spacing.md },
  orLine: { backgroundColor: colors.line, flex: 1, height: 1 },
  orText: { color: colors.textDim, fontSize: 8, fontWeight: '800', letterSpacing: 0.7 },
  section: { marginTop: spacing.xl },
  healthGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  healthTile: { minHeight: 112, padding: spacing.md, width: '48.5%' },
  healthTop: { alignItems: 'center', flexDirection: 'row', justifyContent: 'space-between' },
  healthDot: { borderRadius: 4, height: 7, width: 7 },
  healthValue: { color: colors.text, fontSize: 22, fontWeight: '700', marginTop: spacing.md },
  healthLabel: { color: colors.textMuted, fontSize: 10, fontWeight: '700', marginTop: 2 },
  controlCard: { padding: spacing.lg },
  infoRow: { alignItems: 'center', borderBottomColor: colors.line, borderBottomWidth: 1, flexDirection: 'row', justifyContent: 'space-between', minHeight: 46 },
  infoLabelRow: { alignItems: 'center', flexDirection: 'row', gap: 9 },
  infoLabel: { color: colors.textMuted, fontSize: 12, fontWeight: '600' },
  infoValue: { color: colors.text, fontSize: 12, fontWeight: '800' },
  actionRow: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.lg },
  actionButton: { flex: 1 },
  calibrationCard: { alignItems: 'center', flexDirection: 'row', padding: spacing.md },
  calibrationIcon: { alignItems: 'center', backgroundColor: '#192219', borderRadius: 17, height: 46, justifyContent: 'center', marginRight: 12, width: 46 },
  calibrationCopy: { flex: 1, paddingRight: spacing.sm },
  calibrationTitle: { color: colors.text, fontSize: 14, fontWeight: '700' },
  calibrationBody: { color: colors.textMuted, fontSize: 10, lineHeight: 15, marginTop: 4 },
  disconnectButton: { marginTop: spacing.xl },
  tipCard: { alignItems: 'flex-start', flexDirection: 'row', marginTop: spacing.md, padding: spacing.md },
  tipIcon: { alignItems: 'center', backgroundColor: '#142322', borderRadius: 16, height: 40, justifyContent: 'center', marginRight: 11, width: 40 },
  tipCopy: { flex: 1 },
  tipTitle: { color: colors.text, fontSize: 13, fontWeight: '700' },
  tipBody: { color: colors.textMuted, fontSize: 11, lineHeight: 16, marginTop: 4 },
  version: { color: colors.textDim, fontSize: 9, fontWeight: '800', letterSpacing: 1.2, marginTop: spacing.xl, textAlign: 'center' },
});
