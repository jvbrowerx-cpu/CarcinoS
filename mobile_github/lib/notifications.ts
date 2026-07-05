/**
 * CarcinoS — Push Notification Registration
 *
 * Requests push permission from the OS and saves the Expo push token
 * to Supabase via the store_push_token() RPC.
 *
 * Call registerForPushNotifications() once after the user is authenticated.
 * It is safe to call multiple times — it no-ops on simulators and if
 * permission was already denied.
 */

import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';
import { supabase, DEMO_MODE } from './supabase';

// How notifications appear when the app is in the foreground
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: false,
    shouldSetBadge: true,
  }),
});

/**
 * Request push permission and store the Expo token in Supabase.
 * Returns the token string on success, null if permission was denied
 * or if running in a simulator / demo mode.
 */
export async function registerForPushNotifications(): Promise<string | null> {
  // Skip in demo mode or on simulators (push doesn't work there)
  if (DEMO_MODE || !supabase) return null;
  if (!Device.isDevice) {
    console.log('[Push] Skipping — simulator detected');
    return null;
  }

  // Android requires a notification channel
  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync('carcinos-alerts', {
      name: 'CarcinoS Alerts',
      importance: Notifications.AndroidImportance.HIGH,
      vibrationPattern: [0, 250, 250, 250],
      lightColor: '#7a8e7a',
    });
  }

  // Check / request permission
  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;

  if (existingStatus !== 'granted') {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }

  if (finalStatus !== 'granted') {
    console.log('[Push] Permission denied');
    return null;
  }

  // Get the Expo push token
  const tokenData = await Notifications.getExpoPushTokenAsync({
    projectId: process.env.EXPO_PUBLIC_PROJECT_ID,
  });
  const token = tokenData.data;
  console.log('[Push] Expo token:', token);

  // Store in Supabase
  const { error } = await supabase.rpc('store_push_token', { p_token: token });
  if (error) {
    console.warn('[Push] Failed to store token:', error.message);
    return null;
  }

  return token;
}

/**
 * Clear the push token in Supabase when the user signs out.
 * Prevents delivery attempts to stale tokens.
 */
export async function clearPushToken(): Promise<void> {
  if (DEMO_MODE || !supabase) return;
  await supabase.rpc('clear_push_token');
}
