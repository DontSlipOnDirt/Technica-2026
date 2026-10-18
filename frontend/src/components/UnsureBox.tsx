/** Shown when the bank couldn't tell whether the money moved. It never offers to try again. */
export function UnsureBox() {
  return (
    <section className="unsure" role="alert">
      We're not sure this went through. Please check your balance before trying again, or call Capital One.
    </section>
  )
}
