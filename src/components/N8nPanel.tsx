import Ionicons from '@expo/vector-icons/Ionicons';
import React, { useEffect, useState } from 'react';
import { StyleSheet, Text, TextInput, View } from 'react-native';

import { Eyebrow, PrimaryButton, Surface } from '@/components/ui';
import { useN8n } from '@/context/N8nContext';
import { colors, radii, spacing } from '@/theme';

export function N8nPanel() {
  const { config, ready, lastSentAt, saveConfig } = useN8n();
  const [webhookUrl, setWebhookUrl] = useState(config.webhookUrl);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => setWebhookUrl(config.webhookUrl), [config.webhookUrl]);

  const save = async () => {
    setSaving(true);
    setMessage(null);
    setFailed(false);
    try {
      await saveConfig({ webhookUrl });
      setMessage('Webhook saved. Send any camera hit or logged shot from Sessions.');
    } catch (error) {
      setFailed(true);
      setMessage(error instanceof Error ? error.message : 'Could not save the n8n webhook.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Surface style={styles.card}>
      <View style={styles.headingRow}>
        <View style={[styles.logo, ready && styles.logoReady]}>
          <Ionicons name="git-network-outline" size={23} color={ready ? colors.accent : colors.textMuted} />
        </View>
        <View style={styles.headingCopy}>
          <Eyebrow>Webhook output</Eyebrow>
          <Text style={styles.title}>n8n</Text>
          <Text style={styles.status}>{ready ? 'Endpoint configured' : 'Not configured'}</Text>
        </View>
      </View>

      <Text style={styles.inputLabel}>Production webhook URL</Text>
      <View style={styles.inputWrap}>
        <Ionicons name="link-outline" size={18} color={colors.textMuted} />
        <TextInput
          accessibilityLabel="n8n webhook URL"
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          onChangeText={(value) => { setWebhookUrl(value); setMessage(null); }}
          onSubmitEditing={() => void save()}
          placeholder="https://n8n.example.com/webhook/lm1-shot"
          placeholderTextColor={colors.textDim}
          returnKeyType="done"
          selectionColor={colors.accent}
          style={styles.input}
          value={webhookUrl}
        />
      </View>
      <Text style={styles.help}>LM1 sends an HTTP POST containing every stored field for the selected camera hit or shot, plus event and app metadata.</Text>

      {message ? <Text style={[styles.message, failed && styles.messageError]}>{message}</Text> : null}
      {lastSentAt ? <Text style={styles.lastSent}>Last sent {new Date(lastSentAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</Text> : null}
      <PrimaryButton label={saving ? 'Saving…' : 'Save n8n webhook'} icon="save-outline" loading={saving} onPress={() => void save()} variant="outline" />
    </Surface>
  );
}

const styles = StyleSheet.create({
  card: { padding: spacing.lg },
  headingRow: { alignItems: 'center', flexDirection: 'row', marginBottom: spacing.lg },
  logo: { alignItems: 'center', backgroundColor: colors.surfaceRaised, borderRadius: 6, height: 52, justifyContent: 'center', marginRight: 13, width: 52 },
  logoReady: { backgroundColor: colors.accentWash },
  headingCopy: { flex: 1 },
  title: { color: colors.text, fontSize: 18, fontWeight: '700', marginTop: 3 },
  status: { color: colors.textMuted, fontSize: 11, fontWeight: '600', marginTop: 3 },
  inputLabel: { color: colors.textMuted, fontSize: 10, fontWeight: '800', letterSpacing: 0.8, marginBottom: 7, textTransform: 'uppercase' },
  inputWrap: { alignItems: 'center', backgroundColor: colors.background, borderColor: colors.lineStrong, borderRadius: radii.md, borderWidth: 1, flexDirection: 'row', gap: 10, minHeight: 54, paddingHorizontal: spacing.md },
  input: { color: colors.text, flex: 1, fontSize: 13, fontWeight: '600', paddingVertical: 0 },
  help: { color: colors.textDim, fontSize: 10, lineHeight: 15, marginBottom: spacing.md, marginTop: spacing.sm },
  message: { color: colors.accent, fontSize: 10, fontWeight: '700', lineHeight: 15, marginBottom: spacing.sm },
  messageError: { color: colors.red },
  lastSent: { color: colors.textMuted, fontSize: 10, fontWeight: '700', marginBottom: spacing.sm },
});
