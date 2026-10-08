import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Platform, StyleSheet, Text, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { useFonts } from 'expo-font';
import { StatusBar } from 'expo-status-bar';

import { BottomNav, PlayMode } from '@/components/BottomNav';
import { ShotDetailModal } from '@/components/ShotDetailModal';
import { LaunchMonitorProvider, useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { CloudSyncProvider, useCloudSync } from '@/context/CloudSyncContext';
import { N8nProvider } from '@/context/N8nContext';
import { OpenGolfSimProvider } from '@/context/OpenGolfSimContext';
import { UnitsProvider } from '@/context/UnitsContext';
import { DeviceScreen } from '@/screens/DeviceScreen';
import { CalculatorScreen } from '@/screens/CalculatorScreen';
import { CloudAccountScreen } from '@/screens/CloudAccountScreen';
import { CalibrationScreen } from '@/screens/CalibrationScreen';
import { HistoryScreen } from '@/screens/HistoryScreen';
import { HomeScreen } from '@/screens/HomeScreen';
import { PuttingScreen } from '@/screens/PuttingScreen';
import { colors } from '@/theme';
import { AppTab, Shot } from '@/types';
import { applyAppFont, fontAssets } from '@/typography';

export default function App() {
  const [fontsLoaded, fontError] = useFonts(fontAssets);
  if (!fontsLoaded && !fontError) return <View style={styles.authLoading} />;
  if (fontsLoaded) applyAppFont();
  return (
    <SafeAreaProvider>
      <CloudSyncProvider>
        <StatusBar style="light" />
        <AuthenticationGate />
      </CloudSyncProvider>
    </SafeAreaProvider>
  );
}

function AuthenticationGate() {
  const { authReady, session } = useCloudSync();
  if (!authReady) {
    return <View style={styles.authLoading}><ActivityIndicator color={colors.accent} /><Text style={styles.authLoadingText}>Restoring your account…</Text></View>;
  }
  if (!session) return <View style={styles.authRoot}><CloudAccountScreen /></View>;
  return (
    <UnitsProvider>
      <OpenGolfSimProvider>
        <N8nProvider>
          <LaunchMonitorProvider>
            <AppShell />
          </LaunchMonitorProvider>
        </N8nProvider>
      </OpenGolfSimProvider>
    </UnitsProvider>
  );
}

function AppShell() {
  const { arm, ballDetected, captureMode, liveShot, selectShot } = useLaunchMonitor();
  const [tab, setTab] = useState<AppTab>('home');
  const [playMode, setPlayMode] = useState<PlayMode>(captureMode === 'putting' ? 'putting' : 'swing');
  const [detailShot, setDetailShot] = useState<Shot | null>(null);
  const shownLiveShotId = useRef<string | null>(null);

  useEffect(() => {
    if (!liveShot) return;
    if (shownLiveShotId.current === liveShot.id) {
      setDetailShot((current) => current?.id === liveShot.id ? liveShot : current);
      return;
    }
    shownLiveShotId.current = liveShot.id;
    selectShot(liveShot);
    setTab('home');
    setPlayMode('swing');
    setDetailShot(liveShot);
  }, [liveShot, selectShot]);

  const openShot = (shot: Shot) => {
    selectShot(shot);
    setDetailShot(shot);
  };

  return (
    <View style={styles.root}>
      <View style={styles.screen}>
        {tab === 'home' && playMode === 'swing' ? (
          <HomeScreen
            onOpenDevice={() => setTab('device')}
            onOpenHistory={() => setTab('history')}
            onOpenShot={openShot}
          />
        ) : tab === 'home' ? (
          <PuttingScreen
            onOpenDevice={() => setTab('device')}
            onOpenNormalShot={() => { void arm(); setPlayMode('swing'); }}
          />
        ) : tab === 'calibration' ? (
          <CalibrationScreen />
        ) : tab === 'history' ? (
          <HistoryScreen onOpenShot={openShot} onOpenCalculator={() => setTab('calculator')} />
        ) : tab === 'calculator' ? (
          <CalculatorScreen />
        ) : tab === 'device' ? (
          <DeviceScreen />
        ) : (
          <CloudAccountScreen />
        )}
      </View>
      <BottomNav active={tab} onChange={setTab} playMode={playMode} onPlayModeChange={setPlayMode} />
      <ShotDetailModal shot={detailShot} onClose={() => setDetailShot(null)} />
      {ballDetected ? <View pointerEvents="none" style={styles.ballDetectedBorder} /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    backgroundColor: colors.background,
    flex: 1,
    ...(Platform.OS === 'web' ? { maxWidth: 520, width: '100%', alignSelf: 'center' } : null),
  },
  authRoot: { backgroundColor: colors.background, flex: 1, justifyContent: 'center', padding: 20 },
  authLoading: { alignItems: 'center', backgroundColor: colors.background, flex: 1, gap: 12, justifyContent: 'center' },
  authLoadingText: { color: colors.textMuted, fontSize: 14 },
  screen: { flex: 1 },
  ballDetectedBorder: {
    borderColor: colors.green,
    borderWidth: 5,
    bottom: 0,
    left: 0,
    position: 'absolute',
    right: 0,
    top: 0,
    zIndex: 100,
  },
});
