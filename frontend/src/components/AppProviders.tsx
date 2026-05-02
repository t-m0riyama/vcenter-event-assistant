import type { ReactNode } from 'react'
import { TimeZoneProvider } from '../datetime/TimeZoneProvider'
import { AutoRefreshPreferencesProvider } from '../preferences/AutoRefreshPreferencesProvider'
import { ChatMaxStoredMessagesProvider } from '../preferences/ChatMaxStoredMessagesProvider'
import { ChatSamplePromptsProvider } from '../preferences/ChatSamplePromptsProvider'
import { SummaryTopNotableMinScoreProvider } from '../preferences/SummaryTopNotableMinScoreProvider'
import { ThemeProvider } from '../theme/ThemeProvider'

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider>
      <TimeZoneProvider>
        <AutoRefreshPreferencesProvider>
          <SummaryTopNotableMinScoreProvider>
            <ChatMaxStoredMessagesProvider>
              <ChatSamplePromptsProvider>{children}</ChatSamplePromptsProvider>
            </ChatMaxStoredMessagesProvider>
          </SummaryTopNotableMinScoreProvider>
        </AutoRefreshPreferencesProvider>
      </TimeZoneProvider>
    </ThemeProvider>
  )
}
