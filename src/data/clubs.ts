import { ClubId } from '@/types';

export type ClubCategory = 'Woods' | 'Hybrids' | 'Irons' | 'Wedges';

export interface ClubDefinition {
  id: ClubId;
  label: string;
  shortLabel: string;
  category: ClubCategory;
  carryFactor: number;
  demoClubSpeedMps: number;
  demoSmash: number;
  demoLaunchDeg: number;
}

export const clubs: ClubDefinition[] = [
  { id: 'driver', label: 'Driver', shortLabel: 'DR', category: 'Woods', carryFactor: 1.1, demoClubSpeedMps: 42, demoSmash: 1.46, demoLaunchDeg: 14 },
  { id: '3-wood', label: '3 Wood', shortLabel: '3W', category: 'Woods', carryFactor: 1.08, demoClubSpeedMps: 40.5, demoSmash: 1.44, demoLaunchDeg: 13.5 },
  { id: '5-wood', label: '5 Wood', shortLabel: '5W', category: 'Woods', carryFactor: 1.05, demoClubSpeedMps: 39.5, demoSmash: 1.42, demoLaunchDeg: 15 },
  { id: '3-hybrid', label: '3 Hybrid', shortLabel: '3H', category: 'Hybrids', carryFactor: 1.02, demoClubSpeedMps: 39, demoSmash: 1.4, demoLaunchDeg: 16 },
  { id: '4-hybrid', label: '4 Hybrid', shortLabel: '4H', category: 'Hybrids', carryFactor: 1, demoClubSpeedMps: 38, demoSmash: 1.38, demoLaunchDeg: 17 },
  { id: '4-iron', label: '4 Iron', shortLabel: '4i', category: 'Irons', carryFactor: 0.98, demoClubSpeedMps: 37.5, demoSmash: 1.37, demoLaunchDeg: 16 },
  { id: '5-iron', label: '5 Iron', shortLabel: '5i', category: 'Irons', carryFactor: 0.97, demoClubSpeedMps: 36.8, demoSmash: 1.35, demoLaunchDeg: 17 },
  { id: '6-iron', label: '6 Iron', shortLabel: '6i', category: 'Irons', carryFactor: 0.96, demoClubSpeedMps: 36, demoSmash: 1.33, demoLaunchDeg: 18 },
  { id: '7-iron', label: '7 Iron', shortLabel: '7i', category: 'Irons', carryFactor: 0.94, demoClubSpeedMps: 35, demoSmash: 1.31, demoLaunchDeg: 19 },
  { id: '8-iron', label: '8 Iron', shortLabel: '8i', category: 'Irons', carryFactor: 0.9, demoClubSpeedMps: 34, demoSmash: 1.29, demoLaunchDeg: 21 },
  { id: '9-iron', label: '9 Iron', shortLabel: '9i', category: 'Irons', carryFactor: 0.87, demoClubSpeedMps: 33, demoSmash: 1.27, demoLaunchDeg: 24 },
  { id: 'pitching-wedge', label: 'Pitching Wedge', shortLabel: 'PW', category: 'Wedges', carryFactor: 0.82, demoClubSpeedMps: 31.5, demoSmash: 1.24, demoLaunchDeg: 28 },
  { id: 'gap-wedge', label: 'Gap Wedge', shortLabel: 'GW', category: 'Wedges', carryFactor: 0.78, demoClubSpeedMps: 29, demoSmash: 1.2, demoLaunchDeg: 32 },
  { id: 'sand-wedge', label: 'Sand Wedge', shortLabel: 'SW', category: 'Wedges', carryFactor: 0.72, demoClubSpeedMps: 27, demoSmash: 1.16, demoLaunchDeg: 35 },
  { id: 'lob-wedge', label: 'Lob Wedge', shortLabel: 'LW', category: 'Wedges', carryFactor: 0.66, demoClubSpeedMps: 25, demoSmash: 1.1, demoLaunchDeg: 38 },
];

export const clubCategories: ClubCategory[] = ['Woods', 'Hybrids', 'Irons', 'Wedges'];

const clubsById = new Map<ClubId, ClubDefinition>(clubs.map((club) => [club.id, club]));

export function getClub(clubId: ClubId): ClubDefinition {
  return clubsById.get(clubId) ?? clubs[0]!;
}

export function isClubId(value: string | null): value is ClubId {
  return value !== null && clubsById.has(value as ClubId);
}
