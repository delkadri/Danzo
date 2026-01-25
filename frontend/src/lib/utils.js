export function shortId(id) {
  if (!id) return "";
  return id.slice(0, 6);
}

export function categoryLabel(cat) {
  const map = {
    sport: "Sport",
    song: "Song",
    movies: "Movies",
    geography: "Geography",
    history: "History",
    brand: "Brand"
  };
  return map[cat] ?? cat;
}
