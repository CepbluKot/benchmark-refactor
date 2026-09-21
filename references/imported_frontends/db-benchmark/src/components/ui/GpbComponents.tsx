import React from 'react';
import { LucideIcon, Loader2, X } from 'lucide-react';

/* =========================================================
   GPB UI Button
   ========================================================= */
interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  icon?: LucideIcon;
  isLoading?: boolean;
}

export const Button: React.FC<ButtonProps> = ({
  children,
  variant = 'secondary',
  size = 'md',
  icon: Icon,
  isLoading = false,
  className = '',
  disabled,
  ...props
}) => {
  const baseClasses =
    'inline-flex items-center justify-center font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-[#0F62FE] focus:ring-offset-1 select-none disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer';

  const sizeClasses = {
    sm: 'text-xs h-7 px-2.5 rounded gap-1.5',
    md: 'text-sm h-9 px-3.5 rounded gap-2',
    lg: 'text-base h-10 px-4 rounded gap-2',
  }[size];

  const variantClasses = {
    primary:
      'bg-[#0033A0] hover:bg-[#002275] active:bg-[#001752] text-white border border-transparent shadow-xs',
    secondary:
      'bg-white dark:bg-[#1E232B] hover:bg-slate-100 dark:hover:bg-[#282F3A] text-slate-800 dark:text-slate-200 border border-slate-300 dark:border-[#38414E]',
    danger:
      'bg-[#DA1E28] hover:bg-[#BA1B23] text-white border border-transparent',
    ghost:
      'bg-transparent hover:bg-slate-100 dark:hover:bg-[#242A33] text-slate-700 dark:text-slate-300 border border-transparent',
  }[variant];

  return (
    <button
      className={`${baseClasses} ${sizeClasses} ${variantClasses} ${className}`}
      disabled={disabled || isLoading}
      {...props}
    >
      {isLoading ? (
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
      ) : Icon ? (
        <Icon className="w-3.5 h-3.5 shrink-0" />
      ) : null}
      <span>{children}</span>
    </button>
  );
};

/* =========================================================
   Status Badge (ADCM / GPB Status Indicators)
   ========================================================= */
export type StatusType =
  | 'ready'
  | 'running'
  | 'completed'
  | 'error'
  | 'unavailable'
  | 'not_checked'
  | 'incomplete'
  | 'neutral';

interface StatusBadgeProps {
  status: StatusType;
  label?: string;
  className?: string;
}

export const StatusBadge: React.FC<StatusBadgeProps> = ({
  status,
  label,
  className = '',
}) => {
  const configs: Record<StatusType, { text: string; bg: string; dot: string }> = {
    ready: {
      text: label || 'Готов',
      bg: 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/60',
      dot: 'bg-emerald-500',
    },
    completed: {
      text: label || 'Завершён',
      bg: 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/60',
      dot: 'bg-emerald-500',
    },
    running: {
      text: label || 'Выполняется',
      bg: 'bg-blue-50 dark:bg-blue-950/40 text-[#0033A0] dark:text-blue-300 border-blue-200 dark:border-blue-800/60',
      dot: 'bg-[#0F62FE] animate-pulse',
    },
    error: {
      text: label || 'Ошибка',
      bg: 'bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-800/60',
      dot: 'bg-rose-500',
    },
    unavailable: {
      text: label || 'Недоступен',
      bg: 'bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-800/60',
      dot: 'bg-rose-500',
    },
    not_checked: {
      text: label || 'Не проверен',
      bg: 'bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800/60',
      dot: 'bg-amber-500',
    },
    incomplete: {
      text: label || 'Не настроен',
      bg: 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-700',
      dot: 'bg-slate-400',
    },
    neutral: {
      text: label || 'Ожидание',
      bg: 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-slate-200 dark:border-slate-700',
      dot: 'bg-slate-400',
    },
  };

  const config = configs[status] || configs.neutral;

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 text-xs font-medium rounded border whitespace-nowrap ${config.bg} ${className}`}
    >
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${config.dot}`} />
      <span>{config.text}</span>
    </span>
  );
};

/* =========================================================
   Form Controls: Input, Select, Textarea
   ========================================================= */
interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  helperText?: string;
  required?: boolean;
}

export const Input: React.FC<InputProps> = ({
  label,
  error,
  helperText,
  required,
  className = '',
  id,
  ...props
}) => {
  const inputId = id || (label ? `input-${label.replace(/\s+/g, '-').toLowerCase()}` : undefined);

  return (
    <div className="flex flex-col gap-1 w-full">
      {label && (
        <label htmlFor={inputId} className="text-xs font-medium text-slate-700 dark:text-slate-300">
          {label} {required && <span className="text-rose-500">*</span>}
        </label>
      )}
      <input
        id={inputId}
        className={`w-full px-3 py-1.5 text-sm bg-white dark:bg-[#1C2129] text-slate-900 dark:text-slate-100 border rounded focus:outline-none focus:ring-1 focus:ring-[#0033A0] dark:focus:ring-blue-500 ${
          error
            ? 'border-rose-500 dark:border-rose-500'
            : 'border-slate-300 dark:border-[#343D4B]'
        } disabled:bg-slate-100 dark:disabled:bg-slate-800 disabled:opacity-60 ${className}`}
        {...props}
      />
      {error && <span className="text-xs text-rose-500">{error}</span>}
      {helperText && !error && (
        <span className="text-[11px] text-slate-500 dark:text-slate-400">{helperText}</span>
      )}
    </div>
  );
};

interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  error?: string;
  helperText?: string;
  required?: boolean;
}

export const Select: React.FC<SelectProps> = ({
  label,
  error,
  helperText,
  required,
  children,
  className = '',
  id,
  ...props
}) => {
  const selectId = id || (label ? `select-${label.replace(/\s+/g, '-').toLowerCase()}` : undefined);

  return (
    <div className="flex flex-col gap-1 w-full">
      {label && (
        <label htmlFor={selectId} className="text-xs font-medium text-slate-700 dark:text-slate-300">
          {label} {required && <span className="text-rose-500">*</span>}
        </label>
      )}
      <select
        id={selectId}
        className={`w-full px-3 py-1.5 text-sm bg-white dark:bg-[#1C2129] text-slate-900 dark:text-slate-100 border rounded focus:outline-none focus:ring-1 focus:ring-[#0033A0] dark:focus:ring-blue-500 ${
          error
            ? 'border-rose-500 dark:border-rose-500'
            : 'border-slate-300 dark:border-[#343D4B]'
        } disabled:bg-slate-100 dark:disabled:bg-slate-800 disabled:opacity-60 ${className}`}
        {...props}
      >
        {children}
      </select>
      {error && <span className="text-xs text-rose-500">{error}</span>}
      {helperText && !error && (
        <span className="text-[11px] text-slate-500 dark:text-slate-400">{helperText}</span>
      )}
    </div>
  );
};

/* =========================================================
   Modal Window (ADCM Style)
   ========================================================= */
interface ModalProps {
  isOpen: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
  maxWidth?: 'sm' | 'md' | 'lg' | 'xl';
}

export const Modal: React.FC<ModalProps> = ({
  isOpen,
  onClose,
  title,
  subtitle,
  children,
  footer,
  maxWidth = 'md',
}) => {
  if (!isOpen) return null;

  const widthClass = {
    sm: 'max-w-md',
    md: 'max-w-lg',
    lg: 'max-w-2xl',
    xl: 'max-w-4xl',
  }[maxWidth];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/60 backdrop-blur-xs">
      <div
        className={`w-full ${widthClass} bg-white dark:bg-[#191F28] rounded-md shadow-2xl border border-slate-200 dark:border-[#2D3644] flex flex-col overflow-hidden max-h-[90vh]`}
        role="dialog"
        aria-modal="true"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 dark:border-[#2D3644] bg-slate-50 dark:bg-[#1E2530]">
          <div>
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100">{title}</h3>
            {subtitle && (
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">{subtitle}</p>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-200 dark:hover:bg-[#28313F] transition-colors"
            aria-label="Закрыть"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-5 overflow-y-auto space-y-4">{children}</div>

        {/* Footer */}
        {footer && (
          <div className="px-5 py-3.5 border-t border-slate-200 dark:border-[#2D3644] bg-slate-50 dark:bg-[#1E2530] flex items-center justify-end gap-2.5">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
};

/* =========================================================
   Notice & Limitation Alert Banner
   ========================================================= */
interface NoticeBannerProps {
  type?: 'info' | 'warning' | 'error' | 'success';
  title?: string;
  children: React.ReactNode;
  className?: string;
}

export const NoticeBanner: React.FC<NoticeBannerProps> = ({
  type = 'info',
  title,
  children,
  className = '',
}) => {
  const styles = {
    info: 'bg-blue-50/70 dark:bg-blue-950/30 border-blue-200 dark:border-blue-900/60 text-blue-900 dark:text-blue-200',
    warning:
      'bg-amber-50/80 dark:bg-amber-950/30 border-amber-200 dark:border-amber-900/60 text-amber-900 dark:text-amber-200',
    error:
      'bg-rose-50/80 dark:bg-rose-950/30 border-rose-200 dark:border-rose-900/60 text-rose-900 dark:text-rose-200',
    success:
      'bg-emerald-50/80 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-900/60 text-emerald-900 dark:text-emerald-200',
  }[type];

  return (
    <div className={`p-3.5 border rounded-sm text-xs leading-relaxed ${styles} ${className}`}>
      {title && <div className="font-semibold mb-1 text-[13px]">{title}</div>}
      <div>{children}</div>
    </div>
  );
};
