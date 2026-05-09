from app.models.schemas import TopicLabel

TOPIC_KEYWORDS: dict[TopicLabel, list[str]] = {
    TopicLabel.politics: ["government", "parliament", "election", "minister", "president", "senate", "vote", "policy", "law"],
    TopicLabel.health: ["hospital", "disease", "vaccine", "medicine", "health", "covid", "doctor", "patient", "cancer", "nhs"],
    TopicLabel.tech: ["software", "ai", "artificial intelligence", "startup", "app", "tech", "google", "apple", "robot", "openai"],
    TopicLabel.finance: ["stock", "market", "economy", "inflation", "bank", "crypto", "bitcoin", "investment", "gdp", "trade"],
    TopicLabel.sports: ["football", "soccer", "basketball", "tennis", "cricket", "olympics", "championship", "league", "match"],
    TopicLabel.transport: ["train", "flight", "airline", "airport", "road", "traffic", "bus", "subway", "metro", "transit"],
    TopicLabel.weather: ["storm", "hurricane", "flood", "temperature", "climate", "rain", "snow", "drought", "earthquake", "forecast"],
    TopicLabel.local: ["city", "town", "council", "mayor", "neighbourhood", "local", "district", "community", "residents"],
    TopicLabel.entertainment: ["movie", "film", "music", "celebrity", "award", "concert", "album", "actor", "netflix", "hollywood"],
    TopicLabel.science: ["research", "study", "scientist", "space", "nasa", "planet", "discovery", "experiment", "biology"],
}

FALLBACK_IMAGES: dict[TopicLabel, str] = {
    TopicLabel.politics: "https://images.unsplash.com/photo-1529107386315-e1a2ed48a620?w=800&q=80",
    TopicLabel.health: "https://images.unsplash.com/photo-1579684385127-1ef15d508118?w=800&q=80",
    TopicLabel.tech: "https://images.unsplash.com/photo-1518770660439-4636190af475?w=800&q=80",
    TopicLabel.finance: "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?w=800&q=80",
    TopicLabel.sports: "https://images.unsplash.com/photo-1461896836934-ffe607ba8211?w=800&q=80",
    TopicLabel.transport: "https://images.unsplash.com/photo-1544620347-c4fd4a3d5957?w=800&q=80",
    TopicLabel.weather: "https://images.unsplash.com/photo-1504608524841-42584120d693?w=800&q=80",
    TopicLabel.local: "https://images.unsplash.com/photo-1477959858617-67f85cf4f1df?w=800&q=80",
    TopicLabel.entertainment: "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?w=800&q=80",
    TopicLabel.science: "https://images.unsplash.com/photo-1446776811953-b23d57bd21aa?w=800&q=80",
    TopicLabel.general: "https://images.unsplash.com/photo-1504711434969-e33886168f5c?w=800&q=80",
}


def classify_topic(title: str, content: str = "") -> TopicLabel:
    text = (title + " " + content).lower()
    scores: dict[TopicLabel, int] = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        if score:
            scores[topic] = score
    if not scores:
        return TopicLabel.general
    return max(scores, key=lambda t: scores[t])


def get_fallback_image(topic: TopicLabel) -> str:
    return FALLBACK_IMAGES.get(topic, FALLBACK_IMAGES[TopicLabel.general])
