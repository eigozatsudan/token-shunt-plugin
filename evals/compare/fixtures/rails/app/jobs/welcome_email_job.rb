class WelcomeEmailJob < ApplicationJob
  queue_as :default

  def perform(user)
    UserMailer.welcome(user).deliver_now
  end
end
