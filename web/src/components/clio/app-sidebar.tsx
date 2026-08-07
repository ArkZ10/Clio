import { Link, useRouterState } from "@tanstack/react-router";
import {
  MessageSquare,
  Library,
  Compass,
  Settings,
  BookOpenCheck,
  Network,
} from "lucide-react";
import { cn } from "@/lib/utils";

const items = [
  { to: "/", label: "Chat", icon: MessageSquare },
  { to: "/library", label: "Library", icon: Library },
  { to: "/explore", label: "Explore", icon: Compass },
  { to: "/vault", label: "Vault", icon: Network },
] as const;

export function AppSidebar() {
  const pathname = useRouterState({ select: (s) => s.location.pathname });

  return (
    <aside className="flex shrink-0 flex-col border-r border-border bg-sidebar md:h-screen md:w-60">
      <div className="flex items-center gap-2.5 px-5 py-6">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-primary">
          <BookOpenCheck className="h-4.5 w-4.5 text-primary-foreground" />
        </span>
        <span className="text-lg font-semibold tracking-tight text-sidebar-foreground">Clio</span>
      </div>

      <nav className="flex gap-1 px-3 md:flex-col">
        {items.map((item) => {
          const active = item.to === "/" ? pathname === "/" : pathname.startsWith(item.to);
          return (
            <Link
              key={item.to}
              to={item.to}
              className={cn(
                "flex flex-1 items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                active
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-secondary/40 hover:text-sidebar-foreground",
              )}
            >
              <item.icon className="h-4.5 w-4.5 shrink-0" />
              <span>{item.label}</span>
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto hidden border-t border-sidebar-border p-3 md:block">
        <Link
          to="/settings"
          className={cn(
            "flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm transition-colors",
            pathname === "/settings"
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:bg-secondary/40 hover:text-sidebar-foreground",
          )}
        >
          <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-secondary text-xs font-semibold text-secondary-foreground">
            AR
          </span>
          <span className="min-w-0 flex-1 truncate">Ada Reyes</span>
          <Settings className="h-4 w-4 shrink-0" />
        </Link>
      </div>
    </aside>
  );
}
