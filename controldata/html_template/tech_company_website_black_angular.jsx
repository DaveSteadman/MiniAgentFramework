export default function TechCompanyWebsite() {
  return (
    <div className="min-h-screen bg-black text-white selection:bg-white selection:text-black">
      <header className="sticky top-0 z-50 border-b border-white/10 bg-black/85 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4 lg:px-8">
          <div className="flex items-center gap-4">
            <div className="flex h-11 w-11 items-center justify-center border border-white/20 bg-zinc-950">
              <div className="h-5 w-5 rotate-45 border border-white/60" />
            </div>
            <div>
              <div className="text-sm uppercase tracking-[0.35em] text-white/55">Tech Company</div>
              <div className="text-lg font-semibold tracking-[0.12em]">KORE74</div>
            </div>
          </div>

          <nav className="hidden gap-8 text-sm uppercase tracking-[0.2em] text-white/70 md:flex">
            <a href="#capabilities" className="transition hover:text-white">Capabilities</a>
            <a href="#systems" className="transition hover:text-white">Systems</a>
            <a href="#work" className="transition hover:text-white">Work</a>
            <a href="#contact" className="transition hover:text-white">Contact</a>
          </nav>
        </div>
      </header>

      <main>
        <section className="relative overflow-hidden border-b border-white/10">
          <div className="absolute inset-0 bg-[linear-gradient(135deg,rgba(255,255,255,0.08)_1px,transparent_1px),linear-gradient(315deg,rgba(255,255,255,0.04)_1px,transparent_1px)] bg-[size:48px_48px] opacity-30" />
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(255,255,255,0.12),transparent_28%),radial-gradient(circle_at_bottom_left,rgba(255,255,255,0.07),transparent_22%)]" />

          <div className="relative mx-auto grid max-w-7xl gap-12 px-6 py-24 lg:grid-cols-[1.15fr_0.85fr] lg:px-8 lg:py-32">
            <div className="max-w-3xl">
              <div className="mb-6 inline-flex items-center gap-3 border border-white/15 bg-white/5 px-4 py-2 text-xs uppercase tracking-[0.28em] text-white/70">
                <span className="h-2 w-2 rotate-45 bg-white" />
                Engineered Systems
              </div>

              <h1 className="max-w-4xl text-5xl font-semibold uppercase leading-[0.95] tracking-[0.04em] sm:text-6xl lg:text-7xl">
                Sharp software for
                <span className="block text-white/55">hard technical problems</span>
              </h1>

              <p className="mt-8 max-w-2xl text-base leading-7 text-white/70 sm:text-lg">
                A black-field, high-contrast digital presence for a company building advanced tools,
                data systems, and applied software. Minimal copy. Clear edges. No soft consumer fluff.
              </p>

              <div className="mt-10 flex flex-col gap-4 sm:flex-row">
                <a
                  href="#contact"
                  className="inline-flex items-center justify-center border border-white bg-white px-6 py-3 text-sm font-medium uppercase tracking-[0.22em] text-black transition hover:bg-transparent hover:text-white"
                >
                  Start a Project
                </a>
                <a
                  href="#work"
                  className="inline-flex items-center justify-center border border-white/20 px-6 py-3 text-sm font-medium uppercase tracking-[0.22em] text-white transition hover:border-white/60 hover:bg-white/5"
                >
                  View Work
                </a>
              </div>
            </div>

            <div className="flex items-stretch">
              <div className="relative w-full overflow-hidden border border-white/15 bg-zinc-950 p-6">
                <div className="absolute right-0 top-0 h-24 w-24 border-l border-b border-white/15" />
                <div className="absolute bottom-0 left-0 h-24 w-24 border-r border-t border-white/15" />

                <div className="grid h-full gap-4">
                  <div className="border border-white/10 bg-black p-5">
                    <div className="text-xs uppercase tracking-[0.28em] text-white/45">Focus</div>
                    <div className="mt-3 text-2xl font-semibold uppercase tracking-[0.08em]">Systems</div>
                  </div>
                  <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1 xl:grid-cols-2">
                    {[
                      ["01", "Platform Engineering"],
                      ["02", "AI & Automation"],
                      ["03", "Mapping & Visualisation"],
                      ["04", "Secure Workflows"],
                    ].map(([id, label]) => (
                      <div key={id} className="border border-white/10 bg-white/[0.03] p-5">
                        <div className="text-xs uppercase tracking-[0.28em] text-white/40">{id}</div>
                        <div className="mt-6 text-sm font-medium uppercase tracking-[0.16em] text-white/90">
                          {label}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section id="capabilities" className="border-b border-white/10">
          <div className="mx-auto max-w-7xl px-6 py-20 lg:px-8">
            <div className="mb-12 flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
              <div>
                <div className="text-xs uppercase tracking-[0.3em] text-white/45">Capabilities</div>
                <h2 className="mt-4 text-3xl font-semibold uppercase tracking-[0.06em] sm:text-4xl">
                  Built for demanding environments
                </h2>
              </div>
              <p className="max-w-2xl text-sm leading-7 text-white/65">
                The layout uses asymmetry, hard borders, and disciplined spacing to create a technical,
                premium feel. This structure is ready for real content once your positioning and logos are final.
              </p>
            </div>

            <div className="grid gap-px overflow-hidden border border-white/10 bg-white/10 md:grid-cols-2 xl:grid-cols-4">
              {[
                {
                  title: "Custom Platforms",
                  body: "Internal tools, specialist applications, and operational software designed around real workflows.",
                },
                {
                  title: "Applied AI",
                  body: "Task automation, local-first inference, analysis pipelines, and domain-specific orchestration.",
                },
                {
                  title: "Data Systems",
                  body: "Structured ingestion, transformation, storage, and retrieval across large technical datasets.",
                },
                {
                  title: "Visual Interfaces",
                  body: "Dashboards, geospatial views, and clear decision surfaces for complex environments.",
                },
              ].map((item) => (
                <div key={item.title} className="bg-black p-8">
                  <div className="mb-6 h-10 w-10 rotate-45 border border-white/30" />
                  <h3 className="text-lg font-semibold uppercase tracking-[0.1em]">{item.title}</h3>
                  <p className="mt-4 text-sm leading-7 text-white/65">{item.body}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="systems" className="border-b border-white/10 bg-zinc-950/40">
          <div className="mx-auto grid max-w-7xl gap-10 px-6 py-20 lg:grid-cols-[0.9fr_1.1fr] lg:px-8">
            <div>
              <div className="text-xs uppercase tracking-[0.3em] text-white/45">Design Direction</div>
              <h2 className="mt-4 text-3xl font-semibold uppercase tracking-[0.06em] sm:text-4xl">
                Black. Angular. Controlled.
              </h2>
              <p className="mt-6 max-w-xl text-sm leading-7 text-white/65">
                This concept is deliberately stripped back. Large typography, thin technical borders,
                chamfer-like geometry, and segmented content blocks give it a strong industrial tone.
              </p>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              {[
                "High-contrast palette",
                "Angular icon language",
                "Asymmetric hero structure",
                "Rigid grid sections",
                "Minimal accent usage",
                "Strong typography hierarchy",
              ].map((item, index) => (
                <div key={item} className="group border border-white/10 bg-black p-6 transition hover:border-white/30 hover:bg-white/[0.03]">
                  <div className="text-xs uppercase tracking-[0.28em] text-white/35">0{index + 1}</div>
                  <div className="mt-8 text-base font-medium uppercase tracking-[0.12em] text-white/90">{item}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section id="work" className="border-b border-white/10">
          <div className="mx-auto max-w-7xl px-6 py-20 lg:px-8">
            <div className="mb-10">
              <div className="text-xs uppercase tracking-[0.3em] text-white/45">Selected Work</div>
              <h2 className="mt-4 text-3xl font-semibold uppercase tracking-[0.06em] sm:text-4xl">
                Placeholder project architecture
              </h2>
            </div>

            <div className="grid gap-6 lg:grid-cols-3">
              {[
                {
                  category: "Platform",
                  title: "Operational Intelligence Stack",
                  text: "Complex-data workflow platform with hardened UX and structured automation pathways.",
                },
                {
                  category: "Geospatial",
                  title: "Terrain and Mapping Engine",
                  text: "Specialist visualisation environment for large-scale spatial datasets and technical overlays.",
                },
                {
                  category: "AI Systems",
                  title: "Local Inference Pipeline",
                  text: "Private, controllable AI orchestration for analysis, retrieval, and workflow execution.",
                },
              ].map((item) => (
                <article key={item.title} className="relative overflow-hidden border border-white/10 bg-zinc-950 p-8">
                  <div className="absolute right-0 top-0 h-16 w-16 border-b border-l border-white/10" />
                  <div className="text-xs uppercase tracking-[0.3em] text-white/40">{item.category}</div>
                  <h3 className="mt-8 text-xl font-semibold uppercase tracking-[0.08em]">{item.title}</h3>
                  <p className="mt-4 text-sm leading-7 text-white/65">{item.text}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="contact">
          <div className="mx-auto max-w-7xl px-6 py-20 lg:px-8">
            <div className="grid gap-8 border border-white/10 bg-zinc-950 p-8 lg:grid-cols-[1fr_auto] lg:items-center lg:p-12">
              <div>
                <div className="text-xs uppercase tracking-[0.3em] text-white/45">Contact</div>
                <h2 className="mt-4 text-3xl font-semibold uppercase tracking-[0.06em] sm:text-4xl">
                  Ready for your real brand assets
                </h2>
                <p className="mt-5 max-w-2xl text-sm leading-7 text-white/65">
                  Swap in the final logo set, tighten the copy around the actual offer, and this can become a
                  polished company landing page quickly.
                </p>
              </div>

              <a
                href="#"
                className="inline-flex items-center justify-center border border-white bg-white px-6 py-3 text-sm font-medium uppercase tracking-[0.22em] text-black transition hover:bg-transparent hover:text-white"
              >
                Enquire
              </a>
            </div>
          </div>
        </section>
      </main>
    </div>
  )
}
