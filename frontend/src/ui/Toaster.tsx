import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import { IconCheck, IconX } from "@tabler/icons-react";

type Toast = { id: number; text: string };
type Api = { success: (text: string) => void };

const ToastContext = createContext<Api>({ success: () => undefined });

export const useToast = () => useContext(ToastContext);

/**
 * Confirmation chips that stack above the bottom bar and fan out on hover,
 * adapted from Arc UI's free toast stack. Errors stay inline, next to the
 * form that caused them; only confirmations travel here.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [open, setOpen] = useState(false);
  const next = useRef(0);
  const dismiss = useCallback(
    (id: number) =>
      setToasts((current) => current.filter((toast) => toast.id !== id)),
    [],
  );
  const success = useCallback(
    (text: string) => {
      const id = ++next.current;
      setToasts((current) => [...current.slice(-2), { id, text }]);
      window.setTimeout(() => dismiss(id), 4200);
    },
    [dismiss],
  );
  const api = useMemo(() => ({ success }), [success]);
  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        className="toast-stack"
        aria-live="polite"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
      >
        <AnimatePresence initial={false}>
          {toasts.map((toast, index) => {
            const depth = toasts.length - 1 - index;
            return (
              <motion.div
                key={toast.id}
                role="status"
                className="toast"
                layout
                initial={{ opacity: 0, y: 24, scale: 0.96 }}
                animate={{
                  opacity: depth > 2 ? 0 : 1,
                  y: open ? -depth * 60 : -depth * 9,
                  scale: open ? 1 : 1 - depth * 0.05,
                }}
                exit={{
                  opacity: 0,
                  y: 12,
                  scale: 0.96,
                  transition: { duration: 0.16 },
                }}
                transition={{ type: "spring", stiffness: 420, damping: 34 }}
                style={{ zIndex: 10 - depth }}
              >
                <span className="toast-mark" aria-hidden="true">
                  <IconCheck size={16} stroke={2.6} />
                </span>
                <span className="toast-text">{toast.text}</span>
                <button
                  type="button"
                  className="toast-close"
                  aria-label="Fechar aviso"
                  onClick={() => dismiss(toast.id)}
                >
                  <IconX size={14} />
                </button>
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}
