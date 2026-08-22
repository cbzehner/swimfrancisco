export interface TempReading {
  stationId: string;
  waterTempC: number;
  waterTempF: number;
  observedAt: string;
}

function roundToTenth(n: number): number {
  return Math.round(n * 10) / 10;
}

// Round each display unit once from the source's native value. Converting
// again later (C→F after an F-native source) would drift 58.4°F to 58.5°F.
export function readingFromC(stationId: string, waterTempC: number, observedAt: string): TempReading {
  return {
    stationId,
    waterTempC: roundToTenth(waterTempC),
    waterTempF: roundToTenth((waterTempC * 9) / 5 + 32),
    observedAt,
  };
}

export function readingFromF(stationId: string, waterTempF: number, observedAt: string): TempReading {
  return {
    stationId,
    waterTempF: roundToTenth(waterTempF),
    waterTempC: roundToTenth(((waterTempF - 32) * 5) / 9),
    observedAt,
  };
}
