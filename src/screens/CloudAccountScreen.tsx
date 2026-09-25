import React, { useState } from 'react';
import { Alert, StyleSheet, Text, TextInput, View } from 'react-native';

import { useCloudSync } from '@/context/CloudSyncContext';
import { colors, radii, spacing } from '@/theme';
import { PrimaryButton, SectionHeader } from '@/components/ui';

export function CloudAccountScreen() {
  const { configured, session, busy, error, notice, signIn, signUp, signOut, resetPassword } = useCloudSync();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  const perform = async (action: () => Promise<void>, success?: string) => {
    try { await action(); if (success) Alert.alert('LM1 cloud', success); }
    catch (caught) { Alert.alert('LM1 cloud', caught instanceof Error ? caught.message : 'Request failed.'); }
  };

  return <View style={styles.container}>
    <SectionHeader title="LM1 Cloud" />
    <Text style={styles.body}>Create an LM1 account or sign in to sync shots, putts and preferences across devices. Offline records upload after sign-in. Account creation may require email confirmation, based on the Supabase project settings.</Text>
    {!configured ? <Text style={styles.error}>Cloud sync needs EXPO_PUBLIC_SUPABASE_URL and EXPO_PUBLIC_SUPABASE_ANON_KEY in the app environment.</Text> : null}
    {session ? <>
      <Text style={styles.signedIn}>Signed in as {session.user.email}</Text>
      <PrimaryButton label="Sign out" onPress={() => void perform(signOut)} variant="outline" />
    </> : <>
      <TextInput accessibilityLabel="Email" autoCapitalize="none" autoComplete="email" keyboardType="email-address" placeholder="Email" placeholderTextColor={colors.textDim} style={styles.input} value={email} onChangeText={setEmail} />
      <TextInput accessibilityLabel="Password" autoComplete="password" placeholder="Password" placeholderTextColor={colors.textDim} secureTextEntry style={styles.input} value={password} onChangeText={setPassword} />
      <PrimaryButton label={busy ? 'Please wait…' : 'Sign in'} disabled={!configured || busy || !email || !password} onPress={() => void perform(() => signIn(email, password))} />
      <PrimaryButton label={busy ? 'Please wait…' : 'Create account'} disabled={!configured || busy || !email || password.length < 8} onPress={() => void perform(() => signUp(email, password), 'Check your email if confirmation is enabled.')} variant="outline" />
      <PrimaryButton label="Forgot password? Send reset email" disabled={!configured || busy || !email} onPress={() => void perform(() => resetPassword(email))} variant="dark" />
    </>}
    {error ? <Text style={styles.error}>{error}</Text> : null}
    {notice ? <Text accessibilityRole="text" style={styles.notice}>{notice}</Text> : null}
  </View>;
}

const styles = StyleSheet.create({
  container: { gap: spacing.md, padding: spacing.lg, backgroundColor: colors.surface, borderRadius: radii.lg, borderWidth: 1, borderColor: colors.line },
  body: { color: colors.textMuted, fontSize: 13, lineHeight: 19 },
  input: { color: colors.text, backgroundColor: colors.background, borderColor: colors.line, borderWidth: 1, borderRadius: radii.md, paddingHorizontal: spacing.md, paddingVertical: spacing.sm },
  signedIn: { color: colors.text, fontSize: 14, fontWeight: '700' },
  error: { color: colors.red, fontSize: 12, lineHeight: 18 },
  notice: { color: colors.accent, fontSize: 12, lineHeight: 18 },
});
