"""Synthetic upstream data for offline builds and contract checks."""
import ipaddress


def source_inputs():
    base = int(ipaddress.ip_address('1.0.0.0'))
    ipv6 = int(ipaddress.ip_address('2400::'))
    return {
        'china_domains': '\n'.join(['domain:' + name for name in
            ('baidu.com', 'qq.com', 'taobao.com', 'jd.com', 'asus.com')]
            + ['domain:domestic' + str(i) + '.example' for i in range(1001)]) + '\n',
        'foreign_domains': '\n'.join(['domain:' + name for name in
            ('google.com', 'gstatic.com', 'wikipedia.org', 'github.com', 'asus.com', 'ts.net')]
            + ['full:foreign' + str(i) + '.example' for i in range(1001)]) + '\n',
        'private_domains': 'full:router.asus.com\ndomain:ts.net\ndomain:lan\n',
        'china_ip': '\n'.join([str(ipaddress.ip_address(base + i)) + '/32' for i in range(1001)]
                              + [str(ipaddress.ip_address(ipv6 + i)) + '/128' for i in range(1001)]) + '\n',
        'advertising_domains': '\n'.join(['domain:doubleclick.net']
            + ['domain:ad' + str(i) + '.example' for i in range(1001)]) + '\n',
    }
