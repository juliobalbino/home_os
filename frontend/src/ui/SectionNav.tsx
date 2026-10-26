import { useEffect, useId, useState } from "react";
import { motion } from "motion/react";

/**
 * In-page jump chips with a sliding glazed indicator (after Arc UI's free
 * tabs). Every section stays mounted; the chips only move the reader and
 * follow the scroll.
 */
export function SectionNav({
  label,
  sections,
}: {
  label: string;
  sections: { id: string; label: string }[];
}) {
  const layoutId = useId();
  const [active, setActive] = useState(sections[0]?.id);
  const key = sections.map((section) => section.id).join("|");

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort(
            (a, b) => a.boundingClientRect.top - b.boundingClientRect.top,
          )[0];
        if (visible) setActive(visible.target.id);
      },
      { rootMargin: "-30% 0px -55% 0px" },
    );
    for (const id of key.split("|")) {
      const element = document.getElementById(id);
      if (element) observer.observe(element);
    }
    // The first section sits above the observer band at the top of the page.
    const first = key.split("|")[0];
    const atTop = () => {
      if (window.scrollY < 40) setActive(first);
    };
    window.addEventListener("scroll", atTop, { passive: true });
    return () => {
      observer.disconnect();
      window.removeEventListener("scroll", atTop);
    };
  }, [key]);

  return (
    <nav className="section-nav" aria-label={label}>
      {sections.map((section) => (
        <a
          key={section.id}
          href={`#${section.id}`}
          className="section-chip"
          aria-current={active === section.id ? "true" : undefined}
          onClick={(event) => {
            event.preventDefault();
            setActive(section.id);
            document
              .getElementById(section.id)
              ?.scrollIntoView?.({ behavior: "smooth", block: "start" });
          }}
        >
          {active === section.id && (
            <motion.span
              layoutId={layoutId}
              className="section-chip-indicator"
              transition={{ type: "spring", stiffness: 500, damping: 38 }}
            />
          )}
          <span className="section-chip-label">{section.label}</span>
        </a>
      ))}
    </nav>
  );
}
