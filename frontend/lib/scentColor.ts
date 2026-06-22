const SCENT_GRADIENTS: Record<string, string> = {
  "Woody Oriental": "linear-gradient(135deg, #B89B7D, #7C6248)",
  "Floral": "linear-gradient(135deg, #E8C2CC, #C77E92)",
  "Aquatic": "linear-gradient(135deg, #B6CDD1, #6F949B)",
  "Citrus Floral": "linear-gradient(135deg, #F0D4A0, #C99A52)",
  "Woody": "linear-gradient(135deg, #9C8567, #5E4C38)",
  "Woody Musk": "linear-gradient(135deg, #C7B6A3, #8B7460)",
  "Green Floral": "linear-gradient(135deg, #C2CFA8, #7F9460)",
  "Fresh Musk": "linear-gradient(135deg, #D6E0DD, #93A8A2)",
  "Floral Woody": "linear-gradient(135deg, #D3A2B0, #7E4F5C)",
  "Powdery Musk": "linear-gradient(135deg, #E5DEE0, #A89AA0)",
};

const DEFAULT_GRADIENT = "linear-gradient(135deg, #DDC5A8, #B8916A)";

export function getScentGradient(origin: string): string {
  return SCENT_GRADIENTS[origin] ?? DEFAULT_GRADIENT;
}
