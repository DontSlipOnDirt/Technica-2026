/** Green confirmation, shown only after the backend says the money actually moved. */
export function SentBox({ text }: { text: string }) {
  return <section className="sent">✓ {text}</section>
}
