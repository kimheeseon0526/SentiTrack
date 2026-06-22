export function formatPrice(priceWon: number): string {
  return `₩${priceWon.toLocaleString("ko-KR")}`;
}
