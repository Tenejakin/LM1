import AsyncStorage from '@react-native-async-storage/async-storage';
import React, { createContext, PropsWithChildren, useCallback, useContext, useEffect, useMemo, useState } from 'react';

import { MPH_PER_MPS } from '@/utils/speed';
import { YARDS_PER_METER } from '@/utils/carry';

export type SpeedUnit = 'kmh' | 'mph';
export type DistanceUnit = 'm' | 'yd';

const SPEED_KEY = 'lm1.units.speed';
const DISTANCE_KEY = 'lm1.units.distance';

const isSpeedUnit = (value: unknown): value is SpeedUnit => value === 'kmh' || value === 'mph';
const isDistanceUnit = (value: unknown): value is DistanceUnit => value === 'm' || value === 'yd';

type UnitsValue = {
  /** True until the saved preference has been read, so nothing flickers on launch. */
  ready: boolean;
  speedUnit: SpeedUnit;
  distanceUnit: DistanceUnit;
  setSpeedUnit: (unit: SpeedUnit) => void;
  setDistanceUnit: (unit: DistanceUnit) => void;
  /** 'km/h' or 'mph' */
  speedLabel: string;
  /** 'm' or 'yd' */
  distanceLabel: string;
  /** Numeric speed in the preferred unit, e.g. "168.4". */
  speed: (metersPerSecond: number, digits?: number) => string;
  /** Speed with its unit, e.g. "168.4 km/h". */
  speedWithUnit: (metersPerSecond: number, digits?: number) => string;
  /** The same speed in the other unit, for the secondary line. */
  altSpeedWithUnit: (metersPerSecond: number, digits?: number) => string;
  /** Numeric distance in the preferred unit, e.g. "182". */
  distance: (meters: number, digits?: number) => string;
  /** Distance with its unit, e.g. "182 yd". */
  distanceWithUnit: (meters: number, digits?: number) => string;
  /** The same distance in the other unit, for the secondary line. */
  altDistanceWithUnit: (meters: number, digits?: number) => string;
  /** Spelled-out unit for screen readers, e.g. "miles per hour". */
  spokenSpeedLabel: string;
  spokenDistanceLabel: string;
};

const UnitsContext = createContext<UnitsValue | null>(null);

export function UnitsProvider({ children }: PropsWithChildren) {
  const [ready, setReady] = useState(false);
  const [speedUnit, setSpeedUnitState] = useState<SpeedUnit>('kmh');
  const [distanceUnit, setDistanceUnitState] = useState<DistanceUnit>('m');

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [savedSpeed, savedDistance] = await Promise.all([
          AsyncStorage.getItem(SPEED_KEY),
          AsyncStorage.getItem(DISTANCE_KEY),
        ]);
        if (cancelled) return;
        if (isSpeedUnit(savedSpeed)) setSpeedUnitState(savedSpeed);
        if (isDistanceUnit(savedDistance)) setDistanceUnitState(savedDistance);
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const setSpeedUnit = useCallback((unit: SpeedUnit) => {
    setSpeedUnitState(unit);
    void AsyncStorage.setItem(SPEED_KEY, unit);
  }, []);

  const setDistanceUnit = useCallback((unit: DistanceUnit) => {
    setDistanceUnitState(unit);
    void AsyncStorage.setItem(DISTANCE_KEY, unit);
  }, []);

  const value = useMemo<UnitsValue>(() => {
    const speedIn = (unit: SpeedUnit, mps: number) => (unit === 'mph' ? mps * MPH_PER_MPS : mps * 3.6);
    const distanceIn = (unit: DistanceUnit, meters: number) =>
      unit === 'yd' ? meters * YARDS_PER_METER : meters;
    const speedLabelFor = (unit: SpeedUnit) => (unit === 'mph' ? 'mph' : 'km/h');
    const distanceLabelFor = (unit: DistanceUnit) => (unit === 'yd' ? 'yd' : 'm');
    const otherSpeed: SpeedUnit = speedUnit === 'mph' ? 'kmh' : 'mph';
    const otherDistance: DistanceUnit = distanceUnit === 'yd' ? 'm' : 'yd';

    const speed = (mps: number, digits = 1) => speedIn(speedUnit, mps).toFixed(digits);
    const distance = (meters: number, digits = 0) => distanceIn(distanceUnit, meters).toFixed(digits);

    return {
      ready,
      speedUnit,
      distanceUnit,
      setSpeedUnit,
      setDistanceUnit,
      speedLabel: speedLabelFor(speedUnit),
      distanceLabel: distanceLabelFor(distanceUnit),
      speed,
      speedWithUnit: (mps, digits = 1) => `${speed(mps, digits)} ${speedLabelFor(speedUnit)}`,
      altSpeedWithUnit: (mps, digits = 1) =>
        `${speedIn(otherSpeed, mps).toFixed(digits)} ${speedLabelFor(otherSpeed)}`,
      distance,
      distanceWithUnit: (meters, digits = 0) => `${distance(meters, digits)} ${distanceLabelFor(distanceUnit)}`,
      altDistanceWithUnit: (meters, digits = 0) =>
        `${distanceIn(otherDistance, meters).toFixed(digits)} ${distanceLabelFor(otherDistance)}`,
      spokenSpeedLabel: speedUnit === 'mph' ? 'miles per hour' : 'kilometres per hour',
      spokenDistanceLabel: distanceUnit === 'yd' ? 'yards' : 'metres',
    };
  }, [distanceUnit, ready, setDistanceUnit, setSpeedUnit, speedUnit]);

  return <UnitsContext.Provider value={value}>{children}</UnitsContext.Provider>;
}

export function useUnits(): UnitsValue {
  const value = useContext(UnitsContext);
  if (!value) throw new Error('useUnits must be used inside a UnitsProvider');
  return value;
}
