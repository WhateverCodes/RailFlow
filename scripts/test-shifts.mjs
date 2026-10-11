import assert from 'node:assert/strict';
import { withinShift } from '../lib/types.ts';
const t=(d,h)=>`2026-09-${d}T${h}:00:00+05:30`;
const cases=[
 ['A shift boundaries',true,'A (06:00-14:00)',t('07','06'),t('07','14')],
 ['A shift overrun',false,'A (06:00-14:00)',t('07','08'),t('07','15')],
 ['B shift boundaries',true,'B (14:00-22:00)',t('07','14'),t('07','22')],
 ['C shift midnight crossing',true,'C (22:00-06:00)',t('07','23'),t('08','01')],
 ['C shift early morning',true,'C (22:00-06:00)',t('08','01'),t('08','06')],
 ['C shift overrun',false,'C (22:00-06:00)',t('07','23'),t('08','07')],
 ['Multi-day assignment rejected',false,'A (06:00-14:00)',t('07','08'),t('08','10')],
 ['Reversed times rejected',false,'A (06:00-14:00)',t('07','10'),t('07','08')],
 ['Malformed dates rejected',false,'A (06:00-14:00)','bad date',t('07','08')],
];
for(const [name,want,shift,start,end] of cases){assert.equal(withinShift(shift,start,end),want,name);console.log('PASS',name)}
