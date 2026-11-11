-- Run once against the shared MySQL instance (see shared-mysql/README.md).
-- Replace the password, then: kubectl exec -it deploy/mysql -- mysql -uroot -p < init.sql
CREATE DATABASE IF NOT EXISTS `debarras` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'debarras'@'%' IDENTIFIED BY 'CHANGE_ME';
GRANT ALL PRIVILEGES ON `debarras`.* TO 'debarras'@'%';
FLUSH PRIVILEGES;
-- Tables are created by the backend on startup (SQLAlchemy create_all).
