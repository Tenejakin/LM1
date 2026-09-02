import React, { useState } from 'react';
import { Platform, StyleSheet, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { StatusBar } from 'expo-status-bar';

import { BottomNav } from '@/components/BottomNav';
import { ShotDetailModal } from '@/components/ShotDetailModal';
import { LaunchMonitorProvider, useLaunchMonitor } from '@/context/LaunchMonitorContext';
import { OpenGolfSimProvider } from '@/context/OpenGolfSimContext';
import { DeviceScreen } from '@/screens/DeviceScreen';
import { CalculatorScreen } from '@/screens/CalculatorScreen';
import { HistoryScreen } from '@/screens/HistoryScreen';
import { HomeScreen } from '@/screens/HomeScreen';
import { PuttingScreen } from '@/screens/PuttingScreen';
import { colors } from '@/theme';
import { AppTab, Shot } from '@/types';

export default function App() {
  return (
    <SafeAreaProvider>
      <OpenGolfSimProvider>
        <LaunchMonitorProvider>
          <StatusBar style="light" />
          <AppShell />
        </LaunchMonitorProvider>
      </OpenGolfSimProvider>
    </SafeAreaProvider>
  );
}

function AppShell() {
  const { selectShot } = useLaunchMonitor();
  const [tab, setTab] = useState<AppTab>('home');
  const [detailShot, setDetailShot] = useState<Shot | null>(null);

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
        ) : tab === 'calculator' ? (
          <CalculatorScreen />
        ) : tab === 'history' ? (
          <HistoryScreen onOpenShot={openShot} />
        ) : (
          <DeviceScreen />
        )}
      </View>
      <BottomNav active={tab} onChange={setTab} />
      <ShotDetailModal shot={detailShot} onClose={() => setDetailShot(null)} />
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
});
