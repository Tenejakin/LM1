import Ionicons from '@expo/vector-icons/Ionicons';
import React, { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Switch, Text, TextInput, View } from 'react-native';

import { Eyebrow, PrimaryButton, Surface } from '@/components/ui';
import { useOpenGolfSim } from '@/context/OpenGolfSimContext';
import { colors, radii, spacing } from '@/theme';
import { OpenGolfSimConfig, OpenGolfSimMode } from '@/types';

export function OpenGolfSimPanel() {
  const {
    state,
    config,
    error,
    playerClub,
    lastResult,
    lastSentAt,
    connect,
    disconnect,
    setAutoSend,
    sendTestShot,
    clearError,
  } = useOpenGolfSim();
  const [draft, setDraft] = useState(config);

  useEffect(() => {
    setDraft((current) => ({
      ...current,
      mode: config.mode,
      accountEmail: config.accountEmail,
      bridgeAddress: config.bridgeAddress,
    }));
  }, [config.mode, config.accountEmail, config.bridgeAddress]);

  const connected = state === 'connected';
  const connecting = state === 'connecting';

  const updateDraft = <Key extends keyof OpenGolfSimConfig>(
    key: Key,
    value: OpenGolfSimConfig[Key],
  ) => setDraft((current) => ({ ...current, [key]: value }));

  const selectMode = (mode: OpenGolfSimMode) => {
    if (connected || connecting) return;
    updateDraft('mode', mode);
  };

  const toggleAutoSend = (enabled: boolean) => {
    setAutoSend(enabled);
  };

  const connectDraft = () => connect({ ...draft, autoSend: config.autoSend });

  return (
    <Surface style={styles.card}>
      <View style={styles.headingRow}>
        <View style={[styles.logo, connected && styles.logoConnected]}>
          <Ionicons name="golf" size={23} color={connected ? colors.accent : colors.textMuted} />
        </View>
        <View style={styles.headingCopy}>
          <Eyebrow>Simulator output</Eyebrow>
          <Text style={styles.title}>OpenGolfSim</Text>
          <View style={styles.statusRow}>
            <View style={[styles.statusDot, { backgroundColor: statusColor(state) }]} />
            <Text style={styles.statusText}>{statusLabel(state)}</Text>
          </View>
        </View>
      </View>

      <Text style={styles.inputLabel}>Connection type</Text>
      <View accessibilityRole="radiogroup" style={styles.modeRow}>
        <ModeButton
          label="Desktop"
          icon="desktop-outline"
          selected={draft.mode === 'desktop'}
          disabled={connected || connecting}
          onPress={() => selectMode('desktop')}
        />
        <ModeButton
          label="Web"
          icon="cloud-outline"
          selected={draft.mode === 'web'}
          disabled={connected || connecting}
          onPress={() => selectMode('web')}
        />
      </View>

      {draft.mode === 'desktop' ? (
        <>
          <Text style={styles.inputLabel}>Desktop bridge address</Text>
          <View style={styles.inputWrap}>
            <Ionicons name="laptop-outline" size={18} color={colors.textMuted} />
            <TextInput
              accessibilityLabel="OpenGolfSim desktop bridge address"
              autoCapitalize="none"
              autoCorrect={false}
              editable={!connected && !connecting}
              keyboardType="url"
              onChangeText={(value) => updateDraft('bridgeAddress', value)}
              onSubmitEditing={() => void connectDraft()}
              placeholder="192.168.1.50:3112"
              placeholderTextColor={colors.textDim}
              returnKeyType="go"
              selectionColor={colors.accent}
              style={styles.input}
              value={draft.bridgeAddress}
            />
          </View>
          <View style={styles.helpBox}>
            <Ionicons name="terminal-outline" size={17} color={colors.cyan} />
            <Text style={styles.helpText}>
              On the OpenGolfSim PC, run <Text style={styles.code}>npm run ogs:bridge</Text>, then enter that PC’s local IP above.
            </Text>
          </View>
        </>
      ) : (
        <>
          <Text style={styles.inputLabel}>OpenGolfSim account email</Text>
          <View style={styles.inputWrap}>
            <Ionicons name="mail-outline" size={18} color={colors.textMuted} />
            <TextInput
              accessibilityLabel="OpenGolfSim account email"
              autoCapitalize="none"
              autoComplete="email"
              autoCorrect={false}
              editable={!connected && !connecting}
              keyboardType="email-address"
              onChangeText={(value) => updateDraft('accountEmail', value)}
              onSubmitEditing={() => void connectDraft()}
              placeholder="you@example.com"
              placeholderTextColor={colors.textDim}
              returnKeyType="go"
              selectionColor={colors.accent}
              style={styles.input}
              value={draft.accountEmail}
            />
          </View>
          <Text style={styles.webNote}>Direct connection to the experimental OpenGolfSim Web simulator.</Text>
        </>
      )}

      <View style={styles.toggleRow}>
        <View style={styles.toggleCopy}>
          <Text style={styles.toggleTitle}>Automatically send shots</Text>
          <Text style={styles.toggleBody}>Forward each completed Pinpoint shot to the simulator.</Text>
        </View>
        <Switch
          accessibilityLabel="Automatically send shots to OpenGolfSim"
          accessibilityRole="switch"
          onValueChange={toggleAutoSend}
          thumbColor={config.autoSend ? colors.accent : colors.textMuted}
          trackColor={{ false: colors.lineStrong, true: '#506B22' }}
          value={config.autoSend}
        />
      </View>

      {error ? (
        <View style={styles.errorBox}>
          <Ionicons name="alert-circle" size={17} color={colors.red} />
          <Text style={styles.errorText}>{error}</Text>
          <Text accessibilityRole="button" onPress={clearError} style={styles.dismissText}>Dismiss</Text>
        </View>
      ) : null}

      {connected ? (
        <>
          <View style={styles.connectionDetails}>
            <DetailRow label="Mode" value={draft.mode === 'desktop' ? 'Desktop bridge' : 'Web simulator'} />
            {playerClub ? <DetailRow label="Simulator club" value={playerClub} /> : null}
            {lastSentAt ? <DetailRow label="Last sent" value={formatTime(lastSentAt)} /> : null}
            {lastResult ? (
              <DetailRow
                label="Last result"
                value={`${lastResult.carryM.toFixed(0)} m carry · ${lastResult.totalM.toFixed(0)} m total`}
              />
            ) : null}
          </View>
          <Text style={styles.spinNote}>Measured spin is used when available; otherwise Pinpoint sends a club-based spin estimate with a neutral axis.</Text>
          <View style={styles.buttonRow}>
            <View style={styles.buttonCell}>
              <PrimaryButton label="Send test shot" icon="paper-plane-outline" onPress={sendTestShot} variant="outline" />
            </View>
            <View style={styles.buttonCell}>
              <PrimaryButton label="Disconnect" icon="unlink" onPress={disconnect} variant="danger" />
            </View>
          </View>
        </>
      ) : (
        <PrimaryButton
          label={connecting ? 'Connecting…' : 'Connect OpenGolfSim'}
          icon="link"
          loading={connecting}
          onPress={() => void connectDraft()}
        />
      )}
    </Surface>
  );
}

function ModeButton({
  label,
  icon,
  selected,
  disabled,
  onPress,
}: {
  label: string;
  icon: keyof typeof Ionicons.glyphMap;
  selected: boolean;
  disabled: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ checked: selected, disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [styles.modeButton, selected && styles.modeButtonSelected, pressed && styles.pressed]}
    >
      <Ionicons name={icon} size={17} color={selected ? colors.accent : colors.textMuted} />
      <Text style={[styles.modeText, selected && styles.modeTextSelected]}>{label}</Text>
    </Pressable>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.detailRow}>
      <Text style={styles.detailLabel}>{label}</Text>
      <Text style={styles.detailValue}>{value}</Text>
    </View>
  );
}

function statusLabel(state: string): string {
  if (state === 'connected') return 'Connected and ready';
  if (state === 'connecting') return 'Connecting';
  if (state === 'error') return 'Needs attention';
  return 'Not connected';
}

function statusColor(state: string): string {
  if (state === 'connected') return colors.accent;
  if (state === 'connecting') return colors.orange;
  if (state === 'error') return colors.red;
  return colors.textDim;
}

function formatTime(value: string): string {
  return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

const styles = StyleSheet.create({
  card: { padding: spacing.lg },
  headingRow: { alignItems: 'center', flexDirection: 'row', marginBottom: spacing.lg },
  logo: { alignItems: 'center', backgroundColor: colors.surfaceRaised, borderRadius: 20, height: 52, justifyContent: 'center', marginRight: 13, width: 52 },
  logoConnected: { backgroundColor: '#192219' },
  headingCopy: { flex: 1 },
  title: { color: colors.text, fontSize: 18, fontWeight: '700', marginTop: 3 },
  statusRow: { alignItems: 'center', flexDirection: 'row', gap: 6, marginTop: 4 },
  statusDot: { borderRadius: 4, height: 7, width: 7 },
  statusText: { color: colors.textMuted, fontSize: 11, fontWeight: '600' },
  inputLabel: { color: colors.textMuted, fontSize: 10, fontWeight: '800', letterSpacing: 0.8, marginBottom: 7, textTransform: 'uppercase' },
  modeRow: { flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.md },
  modeButton: { alignItems: 'center', backgroundColor: colors.background, borderColor: colors.lineStrong, borderRadius: radii.md, borderWidth: 1, flex: 1, flexDirection: 'row', gap: 8, justifyContent: 'center', minHeight: 48 },
  modeButtonSelected: { backgroundColor: '#1A2118', borderColor: colors.accent },
  modeText: { color: colors.textMuted, fontSize: 12, fontWeight: '800' },
  modeTextSelected: { color: colors.accent },
  pressed: { opacity: 0.72 },
  inputWrap: { alignItems: 'center', backgroundColor: colors.background, borderColor: colors.lineStrong, borderRadius: radii.md, borderWidth: 1, flexDirection: 'row', gap: 10, marginBottom: spacing.sm, minHeight: 54, paddingHorizontal: spacing.md },
  input: { color: colors.text, flex: 1, fontSize: 14, fontWeight: '600', paddingVertical: 0 },
  helpBox: { alignItems: 'flex-start', backgroundColor: '#142322', borderRadius: radii.sm, flexDirection: 'row', gap: 9, marginBottom: spacing.md, padding: 11 },
  helpText: { color: colors.textMuted, flex: 1, fontSize: 10, lineHeight: 15 },
  code: { color: colors.cyan, fontFamily: 'monospace', fontWeight: '700' },
  webNote: { color: colors.textDim, fontSize: 10, lineHeight: 15, marginBottom: spacing.md },
  toggleRow: { alignItems: 'center', borderBottomColor: colors.line, borderBottomWidth: 1, borderTopColor: colors.line, borderTopWidth: 1, flexDirection: 'row', marginBottom: spacing.md, paddingVertical: spacing.md },
  toggleCopy: { flex: 1, paddingRight: spacing.md },
  toggleTitle: { color: colors.text, fontSize: 13, fontWeight: '700' },
  toggleBody: { color: colors.textMuted, fontSize: 10, lineHeight: 15, marginTop: 3 },
  errorBox: { alignItems: 'center', backgroundColor: '#241718', borderRadius: radii.sm, flexDirection: 'row', gap: 8, marginBottom: spacing.md, padding: 11 },
  errorText: { color: '#F0B0AC', flex: 1, fontSize: 11, lineHeight: 16 },
  dismissText: { color: colors.text, fontSize: 10, fontWeight: '800' },
  connectionDetails: { borderBottomColor: colors.line, borderBottomWidth: 1, marginBottom: spacing.sm },
  detailRow: { alignItems: 'center', borderTopColor: colors.line, borderTopWidth: 1, flexDirection: 'row', justifyContent: 'space-between', minHeight: 42 },
  detailLabel: { color: colors.textMuted, fontSize: 11, fontWeight: '600' },
  detailValue: { color: colors.text, flex: 1, fontSize: 11, fontWeight: '800', marginLeft: spacing.md, textAlign: 'right' },
  spinNote: { color: colors.textDim, fontSize: 9, lineHeight: 14, marginBottom: spacing.md },
  buttonRow: { flexDirection: 'row', gap: spacing.sm },
  buttonCell: { flex: 1 },
});
