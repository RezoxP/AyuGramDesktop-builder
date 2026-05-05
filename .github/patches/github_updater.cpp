#include "ayu/utils/github_updater.h"

#include "core/application.h"
#include "core/version.h"
#include "boxes/abstract_box.h"
#include "ui/boxes/confirm_box.h"

#include <QDesktopServices>
#include <QJsonDocument>
#include <QJsonObject>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QTimer>
#include <QUrl>

namespace AyuGitHubUpdater {
namespace {

constexpr auto kCheckDelay = 5000;
constexpr auto kApiUrl = "https://api.github.com/repos/RezoxP/AyuGramDesktop-builder/releases/latest";

bool isNewer(const QString &latest, const QString &current) {
	const auto l = latest.split('.');
	const auto c = current.split('.');
	for (auto i = 0; i < qMin(l.size(), c.size()); ++i) {
		const auto lv = l[i].toInt();
		const auto cv = c[i].toInt();
		if (lv > cv) return true;
		if (lv < cv) return false;
	}
	return l.size() > c.size();
}

void performCheck() {
	auto *manager = new QNetworkAccessManager();
	auto request = QNetworkRequest(QUrl(QString::fromLatin1(kApiUrl)));
	request.setHeader(QNetworkRequest::UserAgentHeader, u"AyuGram-Updater/1.0"_q);
	request.setAttribute(
		QNetworkRequest::RedirectPolicyAttribute,
		QNetworkRequest::NoLessSafeRedirectPolicy);
	request.setTransferTimeout(15000);

	auto *reply = manager->get(request);
	QObject::connect(reply, &QNetworkReply::finished, [reply, manager] {
		reply->deleteLater();
		manager->deleteLater();

		if (reply->error() != QNetworkReply::NoError) {
			return;
		}

		const auto doc = QJsonDocument::fromJson(reply->readAll());
		if (!doc.isObject()) {
			return;
		}

		const auto obj = doc.object();
		auto tagName = obj.value("tag_name").toString();
		const auto latestVersion = tagName.startsWith('v')
			? tagName.mid(1)
			: tagName;
		const auto currentVersion = QString::fromLatin1(AppVersionStr);

		if (latestVersion.isEmpty() || !isNewer(latestVersion, currentVersion)) {
			return;
		}

		auto htmlUrl = obj.value("html_url").toString();
		if (htmlUrl.isEmpty()) {
			htmlUrl = u"https://github.com/RezoxP/AyuGramDesktop-builder/releases/latest"_q;
		}

		crl::on_main([=] {
			const auto url = htmlUrl;
			Ui::show(Ui::MakeConfirmBox({
				.text = u"A new version of AyuGram is available!\n\nCurrent: v%1\nLatest: v%2\n\nWould you like to download it?"_q
					.arg(currentVersion, latestVersion),
				.confirmed = [=] {
					QDesktopServices::openUrl(QUrl(url));
				},
				.confirmText = u"Download"_q,
				.cancelText = u"Later"_q,
			}));
		});
	});
}

}

void start() {
	QTimer::singleShot(kCheckDelay, [] {
		performCheck();
	});
}

}
