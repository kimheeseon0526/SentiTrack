export interface FragranceProfile {
  topNotes: string;
  middleNotes: string;
  baseNotes: string;
  longevity: number;
  sillage: number;
}

const PROFILES: Record<string, FragranceProfile> = {
  "Woody Oriental": {
    topNotes: "Bergamot, Black Pepper",
    middleNotes: "Amber, Oud",
    baseNotes: "Sandalwood, Musk",
    longevity: 5,
    sillage: 4,
  },
  "Floral": {
    topNotes: "Aldehydes, Bergamot",
    middleNotes: "Jasmine, Rose",
    baseNotes: "Sandalwood, Vanilla",
    longevity: 3,
    sillage: 3,
  },
  "Aquatic": {
    topNotes: "Marine, Cucumber",
    middleNotes: "Cedar, Iris",
    baseNotes: "White Musk, Ambergris",
    longevity: 3,
    sillage: 2,
  },
  "Citrus Floral": {
    topNotes: "Bergamot, Neroli",
    middleNotes: "Orange Blossom, Ylang-Ylang",
    baseNotes: "White Musk, Cedar",
    longevity: 2,
    sillage: 2,
  },
  "Woody": {
    topNotes: "Vetiver, Cedarwood",
    middleNotes: "Patchouli, Guaiac Wood",
    baseNotes: "Oakmoss, Amber",
    longevity: 4,
    sillage: 3,
  },
  "Woody Musk": {
    topNotes: "Cardamom, Black Pepper",
    middleNotes: "Cashmere Wood, Iris",
    baseNotes: "Sandalwood, White Musk",
    longevity: 4,
    sillage: 3,
  },
  "Green Floral": {
    topNotes: "Fig Leaf, Green Tea",
    middleNotes: "Peony, White Tea",
    baseNotes: "Cedar, Clean Musk",
    longevity: 3,
    sillage: 2,
  },
  "Fresh Musk": {
    topNotes: "Sea Salt, Grapefruit",
    middleNotes: "Linen, Aldehydes",
    baseNotes: "White Musk, Ambergris",
    longevity: 3,
    sillage: 2,
  },
  "Floral Woody": {
    topNotes: "Rose, Geranium",
    middleNotes: "Patchouli, Iris",
    baseNotes: "Smoked Wood, Musk",
    longevity: 4,
    sillage: 3,
  },
  "Powdery Musk": {
    topNotes: "Iris, Violet",
    middleNotes: "Heliotrope, Peach",
    baseNotes: "Talc, White Musk",
    longevity: 3,
    sillage: 2,
  },
};

const DEFAULT_PROFILE: FragranceProfile = {
  topNotes: "Citrus, Aldehydes",
  middleNotes: "Floral, Spice",
  baseNotes: "Musk, Amber",
  longevity: 3,
  sillage: 3,
};

export function getFragranceProfile(origin: string): FragranceProfile {
  return PROFILES[origin] ?? DEFAULT_PROFILE;
}
