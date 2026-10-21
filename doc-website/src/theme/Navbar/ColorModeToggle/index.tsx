/**
 * Two-state light/dark switch that replaces Docusaurus' three-state button
 * (light → dark → system).
 *
 * - A first visit follows the operating system (respectPrefersColorScheme).
 * - Clicking flips between light and dark. If the new mode matches the
 *   operating system, the stored choice is cleared, so the site keeps
 *   following the system from then on.
 * - The knob position comes from CSS on [data-theme], so it is right before
 *   React hydrates and there is no flash.
 */
import React, {type ReactNode} from 'react';
import clsx from 'clsx';
import useIsBrowser from '@docusaurus/useIsBrowser';
import {useColorMode, useThemeConfig} from '@docusaurus/theme-common';
import IconLightMode from '@theme/Icon/LightMode';
import IconDarkMode from '@theme/Icon/DarkMode';
import type {Props} from '@theme/Navbar/ColorModeToggle';

import styles from './styles.module.css';

function systemColorMode(): 'light' | 'dark' {
  return window.matchMedia('(prefers-color-scheme: dark)').matches
    ? 'dark'
    : 'light';
}

export default function NavbarColorModeToggle({className}: Props): ReactNode {
  const isBrowser = useIsBrowser();
  const {disableSwitch} = useThemeConfig().colorMode;
  const {colorMode, setColorMode} = useColorMode();

  if (disableSwitch) {
    return null;
  }

  const isDark = colorMode === 'dark';

  function toggle() {
    const next = isDark ? 'light' : 'dark';
    // null = "follow the system", so the site keeps reacting to OS changes.
    setColorMode(next === systemColorMode() ? null : next);
  }

  return (
    <button
      type="button"
      role="switch"
      aria-checked={isBrowser ? isDark : undefined}
      aria-label="Dark mode"
      title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
      className={clsx('clean-btn', styles.switch, className)}
      onClick={toggle}
      disabled={!isBrowser}>
      <span className={styles.track}>
        <IconLightMode aria-hidden className={clsx(styles.icon, styles.sun)} />
        <IconDarkMode aria-hidden className={clsx(styles.icon, styles.moon)} />
        <span className={styles.knob} />
      </span>
    </button>
  );
}
