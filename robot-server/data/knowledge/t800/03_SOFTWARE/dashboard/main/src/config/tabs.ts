import {
  LayoutDashboard,
  Video,
  RadioTower,
  Activity,
  Sliders,
  LucideIcon
} from 'lucide-react';

export type TabType = 'overview' | 'perception' | 'hardware' | 'pointcloud' | 'watchdog';

export interface TabConfig {
  id: TabType;
  label: string;
  shortLabel: string;
  icon: LucideIcon;
  order: number;
}

export const DASHBOARD_TABS: TabConfig[] = [
  {
    id: 'overview',
    label: '1. Overview (Cockpit)',
    shortLabel: 'Cockpit',
    icon: LayoutDashboard,
    order: 1
  },
  {
    id: 'perception',
    label: '2. Câmeras & Estéreo',
    shortLabel: 'Câmeras',
    icon: Video,
    order: 2
  },
  {
    id: 'hardware',
    label: '3. Controle & Hardware',
    shortLabel: 'Hardware',
    icon: Sliders,
    order: 3
  },
  {
    id: 'pointcloud',
    label: '4. Mapeamento 3D',
    shortLabel: 'Mapa 3D',
    icon: RadioTower,
    order: 4
  },
  {
    id: 'watchdog',
    label: '5. Watchdog & Diagnóstico',
    shortLabel: 'Watchdog',
    icon: Activity,
    order: 5
  }
];

