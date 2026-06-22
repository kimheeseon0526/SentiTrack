export default function AboutPage() {
  return (
    <main>
      <div className="about-hero">
        <div className="about-inner">
          <p className="hero-eyebrow">About SentiTrack</p>
          <h1 className="about-title">Where Scent Meets Intelligence</h1>
        </div>
      </div>

      <div className="about-body">
        <div className="about-inner">
          <p className="about-lead">
            인간의 감정을 자극하는 섬세한 향기와,
            <br />
            이를 텍스트로 추론하는 AI 기술의 만남.
          </p>

          <div className="about-divider" />

          <h2 className="about-section-title">Our Philosophy</h2>
          <p className="about-text">
            SentiTrack은 향기를 단순한 제품이 아닌, 감정의 언어로 바라봅니다. 우리는 각각의
            향이 어떤 기억을 불러일으키고, 어떤 감정을 촉발하는지에 주목합니다. 그 감정의
            기록을 AI 감성 분석 기술과 결합해, 소비자의 진솔한 경험을 새로운 방식으로
            읽어냅니다.
          </p>

          <h2 className="about-section-title">How It Works</h2>
          <p className="about-text">
            사용자가 리뷰를 남기면, 저희의 자연어 처리 모델이 그 텍스트 안에 담긴 감성의
            방향과 확신도를 실시간으로 분석합니다.{" "}
            <span className="about-highlight">POSITIVE</span>와{" "}
            <span className="about-highlight">NEGATIVE</span>로 분류된 결과는 신뢰도 점수와
            함께 즉시 제공되며, My Archive에서 모든 기록을 한눈에 확인할 수 있습니다.
          </p>

          <h2 className="about-section-title">A Note on Language</h2>
          <p className="about-text">
            현재 분석 모델은 영어 텍스트에 최적화되어 있습니다. 보다 정확한 감성 분석을
            위해 영어로 리뷰를 작성해 주세요. 한국어 지원은 준비 중입니다.
          </p>

          <div className="about-divider" />

          <p className="about-text" style={{ color: "var(--color-text-secondary)" }}>
            SentiTrack — Fragrance Intelligence Platform, 2025
          </p>
        </div>
      </div>
    </main>
  );
}
