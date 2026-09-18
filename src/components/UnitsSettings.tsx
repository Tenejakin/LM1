import React from 'react';
import { StyleSheet, View } from 'react-native';

import { HelpText, SegmentedControl } from '@/components/ui';
import { useUnits, DistanceUnit, SpeedUnit } from '@/context/UnitsContext';
import { spacing } from '@/theme';

/** Lets a player read every screen in the units they actually think in. */
export function UnitsSettings() {
  const { speedUnit, distanceUnit, setSpeedUnit, setDistanceUnit } = useUnits();
  return (
    <View style={styles.root}>
      <SegmentedControl<SpeedUnit>
        label="Speed"
        value={speedUnit}
        options={[
          { value: 'kmh', label: 'km/h' },
          { value: 'mph', label: 'mph' },
        ]}
        onChange={setSpeedUnit}
      />
      <SegmentedControl<DistanceUnit>
        label="Distance"
        value={distanceUnit}
        options={[
          { value: 'm', label: 'Metres' },
          { value: 'yd', label: 'Yards' },
        ]}
        onChange={setDistanceUnit}
      />
      <HelpText>
        Applies to every shot, session and putt in the app. Your choice is remembered.
      </HelpText>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { gap: spacing.md },
});
