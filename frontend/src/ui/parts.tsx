import {
  Alert,
  Skeleton,
  Stack,
  Text,
  Title,
  VisuallyHidden,
} from "@mantine/core";
import type { ReactNode } from "react";
import { motion } from "motion/react";
import { IconAlertTriangle, IconCheck } from "@tabler/icons-react";
import { TileMark, TileRun } from "./Tile";
import type { Motif } from "./Tile";

/** Page title set on a glazed tile, with a band of the area's tiles beneath. */
export function PageHeader({
  motif,
  title,
  id,
  children,
  aside,
}: {
  motif: Motif;
  title: string;
  id?: string;
  children?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <header className="page-header" data-motif={motif}>
      <div className="page-header-row">
        <TileMark motif={motif} size={52} className="page-header-mark" />
        <div className="page-header-text">
          <Title order={1} id={id}>
            {title}
          </Title>
          {children && <div className="page-header-sub">{children}</div>}
        </div>
        {aside && <div className="page-header-aside">{aside}</div>}
      </div>
      <TileRun motifs={[motif]} size={14} className="barrado" />
    </header>
  );
}

/** A content group set as one tile in the grout of its wall. */
export function TileSection({
  title,
  id,
  action,
  children,
  className,
  labelledBy,
  order,
}: {
  title?: string;
  id?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  labelledBy?: string;
  /** Position in the single phone column; desktop columns keep source order. */
  order?: number;
}) {
  const headingId = title && id ? `${id}-title` : undefined;
  return (
    <section
      className={`tile ${className ?? ""}`}
      id={id}
      aria-labelledby={labelledBy ?? headingId}
      style={order ? { order } : undefined}
    >
      {title && (
        <div className="tile-head">
          <Title order={2} id={headingId}>
            {title}
          </Title>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

/** Empty states show the wall with one tile still to be laid. */
export function EmptyState({
  children,
  action,
}: {
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-wall" aria-hidden="true">
        <span />
        <span />
        <span />
        <span className="empty-gap" />
      </div>
      <Stack gap={8} align="flex-start">
        <Text className="empty-text">{children}</Text>
        {action}
      </Stack>
    </div>
  );
}

export function Loading({
  label,
  lines = 3,
}: {
  label: string;
  lines?: number;
}) {
  return (
    <div className="loading">
      <VisuallyHidden>
        <p role="status">{label}</p>
      </VisuallyHidden>
      <Stack gap={10} aria-hidden="true">
        {Array.from({ length: lines }, (_, index) => (
          <Skeleton
            key={index}
            height={18}
            width={`${92 - index * 17}%`}
            radius="xs"
          />
        ))}
      </Stack>
    </div>
  );
}

export function ErrorNote({
  children,
  label,
}: {
  children: ReactNode;
  label?: string;
}) {
  return (
    <Alert
      color="barro"
      variant="light"
      icon={<IconAlertTriangle size={18} />}
      aria-label={label}
      className="error-note"
    >
      {children}
    </Alert>
  );
}

/**
 * The signature moment: a finished item's tile turns over and shows its
 * glazed face, the way a fresh tile is pressed into place.
 */
export function FlipTile({ done, motif }: { done: boolean; motif: Motif }) {
  return (
    <span className="flip" aria-hidden="true">
      <motion.span
        className="flip-inner"
        initial={false}
        animate={{ rotateY: done ? 180 : 0 }}
        transition={{ type: "spring", stiffness: 260, damping: 22 }}
      >
        <span className="flip-face flip-front">
          <TileMark motif={motif} size={36} />
        </span>
        <span className="flip-face flip-back">
          <IconCheck size={20} stroke={3} />
        </span>
      </motion.span>
    </span>
  );
}

/** Ten tiles laid in a row: how much of the month's budget is spent. */
export function TileMeter({ value, total }: { value: number; total: number }) {
  const ratio = total > 0 ? value / total : 0;
  const filled = Math.min(10, Math.round(ratio * 10));
  const over = ratio > 1;
  return (
    <div
      className="meter"
      role="img"
      aria-label={`${Math.round(ratio * 100)}% do orçamento usado`}
      data-over={over || undefined}
    >
      {Array.from({ length: 10 }, (_, index) => (
        <motion.span
          key={index}
          className="meter-cell"
          data-on={index < filled || undefined}
          initial={false}
          animate={{ scale: index < filled ? 1 : 0.86 }}
          transition={{ delay: index * 0.03, duration: 0.2 }}
        />
      ))}
    </div>
  );
}

export function Done({ children }: { children: ReactNode }) {
  return (
    <span className="done-note">
      <IconCheck size={14} stroke={3} aria-hidden="true" />
      {children}
    </span>
  );
}
