import React, { useEffect, useRef, useState } from 'react';
import { Platform, StyleSheet, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';

import { BottomNav } from '@/components/BottomNav';
import { ShotDetailModal } from '@/components/ShotDetailModal';
import { LaunchMonitorProvider, useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { N8nProvider } from '@/context/N8nContext';
import { OpenGolfSimProvider } from '@/context/OpenGolfSimContext';
import { UnitsProvider } from '@/context/UnitsContext';
import { DeviceScreen } from '@/screens/DeviceScreen';
import { CalculatorScreen } from '@/screens/CalculatorScreen';
import { CalibrationScreen } from '@/screens/CalibrationScreen';
import { HistoryScreen } from '@/screens/HistoryScreen';
import { HomeScreen } from '@/screens/HomeScreen';
import { PuttingScreen } from '@/screens/PuttingScreen';
import { colors } from '@/theme';
import { AppTab, Shot } from '@/types';

export default function App() {
  return (
    <SafeAreaProvider>
      <UnitsProvider>
        <OpenGolfSimProvider>
          <N8nProvider>
            <LaunchMonitorProvider>
              <StatusBar style="light" />
              <AppShell />
            </LaunchMonitorProvider>
          </N8nProvider>
        </OpenGolfSimProvider>
      </UnitsProvider>
    </SafeAreaProvider>
  );
}

function AppShell() {
  const { ballDetected, liveShot, selectShot } = useLaunchMonitor();
  const [tab, setTab] = useState<AppTab>('home');
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
    setDetailShot(liveShot);
  }, [liveShot, selectShot]);

  const openShot = (shot: Shot) => {
    selectShot(shot);
    setDetailShot(shot);
  };

  return (
    <View style={styles.root}>
      <View style={styles.screen}>
        {tab === 'home' ? (
          <HomeScreen
            onOpenDevice={() => setTab('device')}
            onOpenHistory={() => setTab('history')}
            onOpenShot={openShot}
          />
        ) : tab === 'putting' ? (
          <PuttingScreen onOpenDevice={() => setTab('device')} />
        ) : tab === 'calibration' ? (
          <CalibrationScreen />
        ) : tab === 'history' ? (
          <HistoryScreen onOpenShot={openShot} onOpenCalculator={() => setTab('calculator')} />
        ) : tab === 'calculator' ? (
          <CalculatorScreen />
        ) : (
          <DeviceScreen />
        )}
      </View>
      <BottomNav active={tab} onChange={setTab} />
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
  screen: { flex: 1 },
  ballDetectedBorder: {
    borderColor: '#35D66B',
    borderWidth: 5,
    bottom: 0,
    left: 0,
    position: 'absolute',
    right: 0,
    top: 0,
    zIndex: 100,
  },
});
