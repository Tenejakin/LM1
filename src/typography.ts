import {
  SpaceGrotesk_300Light,
  SpaceGrotesk_400Regular,
  SpaceGrotesk_500Medium,
  SpaceGrotesk_600SemiBold,
  SpaceGrotesk_700Bold,
} from '@expo-google-fonts/space-grotesk';
import { SpaceMono_400Regular, SpaceMono_700Bold } from '@expo-google-fonts/space-mono';
import { StyleSheet, Text } from 'react-native';

export const fontAssets = {
  SpaceGrotesk_300Light,
  SpaceGrotesk_400Regular,
  SpaceGrotesk_500Medium,
  SpaceGrotesk_600SemiBold,
  SpaceGrotesk_700Bold,
  SpaceMono_400Regular,
  SpaceMono_700Bold,
};

export const MONO_FAMILY = 'SpaceMono_400Regular';

function sansFor(weight: string | number | undefined): string {
  const w = weight === 'bold' ? 700 : weight === 'normal' || weight === undefined ? 400 : Number(weight);
  if (w <= 300) return 'SpaceGrotesk_300Light';
  if (w <= 400) return 'SpaceGrotesk_400Regular';
  if (w <= 500) return 'SpaceGrotesk_500Medium';
  if (w <= 600) return 'SpaceGrotesk_600SemiBold';
  return 'SpaceGrotesk_700Bold';
}

let patched = false;

/**
 * Makes every <Text> use the app fonts. Custom fonts have one file per weight, so the
 * requested fontWeight is mapped to the matching file and then removed from the style.
 * Call once, after the fonts have loaded.
 */
export function applyAppFont() {
  if (patched) return;
  const target = Text as unknown as { render?: (props: any, ref: any) => any };
  const original = target.render;
  if (typeof original !== 'function') return;
  patched = true;
  target.render = function patchedRender(props: any, ref: any) {
    const flat = StyleSheet.flatten(props.style) ?? {};
    const family: string | undefined = flat.fontFamily;
    const isMono = family === MONO_FAMILY || (family !== undefined && family.toLowerCase().includes('mono'));
    let fontFamily = family;
    if (isMono) fontFamily = Number(flat.fontWeight) >= 700 || flat.fontWeight === 'bold' ? 'SpaceMono_700Bold' : MONO_FAMILY;
    else if (!family || family.startsWith('SpaceGrotesk')) fontFamily = sansFor(flat.fontWeight);
    return original.call(this, { ...props, style: [props.style, { fontFamily, fontWeight: undefined }] }, ref);
  };
}
