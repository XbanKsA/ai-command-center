import { Capacitor } from '@capacitor/core'
import { KeepAwake } from '@capacitor-community/keep-awake'
import { StatusBar } from '@capacitor/status-bar'

export async function setupTablet() {
  if (!Capacitor.isNativePlatform()) return // nothing to do in the PC browser
  await KeepAwake.keepAwake().catch(() => {})
  await StatusBar.hide().catch(() => {})
}