module Notifiable
  extend ActiveSupport::Concern

  def deliver_notifications
    WelcomeEmailJob.perform_later(self)
  end
end
